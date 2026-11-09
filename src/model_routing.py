"""Offline, uncalibrated complexity policy; no labels, IDs or reward features.

Profile names describe configured roles, not proven quality/cost superiority.
Fixed mode never escalates. A routed retry is allowed only when the caller
already decided to retry (e.g. a coding patch failed unchanged tests).
"""
import ast
from dataclasses import asdict, dataclass
import re

from src.coding import contract
from src.model_solver import context
from src.task_loader import read_text


ALLOWED_MODELS = ('qwen3.8-27b', 'qwen3.6-35b-a3b')


@dataclass(frozen=True)
class ComplexityFeatures:
    task_type: str
    instruction_bytes: int
    context_bytes: int = 0
    file_count: int = 0
    ast_nodes: int = 0
    branches: int = 0
    control_depth: int = 0
    semantic_steps: int = 0
    complete: bool = True


def features(task, files=None):
    size = len(task.instruction.encode('utf-8'))
    values = dict(task_type=task.task_type, instruction_bytes=size)
    try:
        if task.task_type == 'coding':
            source, tests = contract(task.instruction)
            code = read_text(task.workspace / source, task.workspace)
            test_code = read_text(task.workspace / tests, task.workspace)
            values.update(context_bytes=len(code.encode()) + len(test_code.encode()), file_count=2)
            tree = ast.parse(code)
            nodes = list(ast.walk(tree))
            if len(nodes) > 20000:
                raise ValueError('Complexity AST limit')
            controls = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match,
                        ast.IfExp, ast.comprehension)
            branches = sum(isinstance(node, controls) for node in nodes)
            depth = 0
            pending = [(tree, 0)]
            while pending:
                node, current = pending.pop()
                current += isinstance(node, controls)
                depth = max(depth, current)
                pending.extend((child, current) for child in ast.iter_child_nodes(node))
            values.update(ast_nodes=len(nodes), branches=branches, control_depth=depth)
        else:
            files = context(task) if files is None else files
            values.update(context_bytes=sum(len(text.encode('utf-8')) for text in files.values()),
                          file_count=len(files))
            if task.task_type == 'math':
                pattern = r'[+*/^−-]|\b(?:then|constraint|subject to)\b'
            elif task.task_type == 'search':
                pattern = r"'s\b|\b(?:employer|mentor|manager|headquarters|founder|parent|successor)\b"
            else:
                pattern = r'\b(?:group by|join|merge|pivot|regression|correlation|quantile|rolling|window|aggregate|median)\b'
            values['semantic_steps'] = len(re.findall(pattern, task.instruction, re.I))
    except (OSError, ValueError, UnicodeError, SyntaxError, RecursionError):
        values['complete'] = False
    return ComplexityFeatures(**values)


def complexity_score(value):
    checks = (
        (value.instruction_bytes > 2048, 2), (value.context_bytes > 8192, 2),
        (value.context_bytes > 32768, 2), (value.file_count >= 8, 1),
        (value.ast_nodes > 300, 2), (value.branches >= 4, 2),
        (value.branches >= 10, 2), (value.control_depth >= 3, 2),
        (value.semantic_steps >= 3, 2), (value.semantic_steps >= 6, 2))
    return sum(weight for condition, weight in checks if condition)


@dataclass(frozen=True)
class ModelRouting:
    mode: str = 'fixed'
    fixed_model: str = ALLOWED_MODELS[0]
    easy_model: str = ALLOWED_MODELS[0]
    hard_model: str = ALLOWED_MODELS[1]
    threshold: int = 4

    def __post_init__(self):
        if self.mode not in {'fixed', 'complexity'}:
            raise ValueError('Unknown model selection mode')
        if any(name not in ALLOWED_MODELS for name in (self.fixed_model, self.easy_model, self.hard_model)):
            raise ValueError('Model outside configured Q1 profile')
        if type(self.threshold) is not int or self.threshold < 1:
            raise ValueError('Routing threshold must be a positive integer')

    @property
    def allowed_models(self):
        return frozenset((self.fixed_model,)) if self.mode == 'fixed' else frozenset((self.easy_model, self.hard_model))

    @property
    def primary_model(self):
        return self.fixed_model if self.mode == 'fixed' else self.easy_model

    def bind(self, task, adapter, recorder, files=None):
        if not self.allowed_models <= adapter.allowed_models:
            raise ValueError('Adapter does not permit the routing profile')
        value = features(task, files) if self.mode == 'complexity' else None
        return TaskModel(self, task, adapter, recorder, value)


class TaskModel:
    def __init__(self, policy, task, adapter, recorder, value):
        self.policy, self.adapter, self.recorder = policy, adapter, recorder
        self.scope, self.features = str(task.task_dir), value
        self.attempts = 0

    async def invoke(self, scope, messages, *, output_cap):
        if scope != self.scope:
            raise ValueError('Task routing scope mismatch')
        score = complexity_score(self.features) if self.features else None
        if self.policy.mode == 'fixed':
            model, reason, level = self.policy.fixed_model, 'fixed_model', 'unclassified'
        elif not self.features.complete:
            model, reason, level = self.policy.hard_model, 'incomplete_features', 'unknown'
        elif score >= self.policy.threshold:
            model, reason, level = self.policy.hard_model, 'complexity_threshold', 'complex'
        else:
            model, reason, level = self.policy.easy_model, 'simple_features', 'simple'
        if self.policy.mode == 'complexity' and self.attempts:
            model, reason = self.policy.hard_model, 'retry_after_failed_verification'
        self.recorder.emit('model_selected', scope, model=model, mode=self.policy.mode,
            complexity=level, score=score, threshold=self.policy.threshold, reason=reason,
            attempt=self.attempts, features=asdict(self.features) if self.features else {},
            policy_version='complexity-v1-uncalibrated')
        self.attempts += 1
        return await self.adapter.invoke(scope, messages, output_cap=output_cap, model_name=model)


def add_arguments(parser):
    parser.add_argument('--model-mode', choices=['fixed', 'complexity'], default='fixed')
    parser.add_argument('--easy-model', choices=ALLOWED_MODELS, default=ALLOWED_MODELS[0])
    parser.add_argument('--hard-model', choices=ALLOWED_MODELS, default=ALLOWED_MODELS[1])
    parser.add_argument('--routing-threshold', type=int, default=4)


def from_arguments(args):
    return ModelRouting(mode=getattr(args, 'model_mode', 'fixed'),
        fixed_model=getattr(args, 'model', None) or ALLOWED_MODELS[0],
        easy_model=getattr(args, 'easy_model', ALLOWED_MODELS[0]),
        hard_model=getattr(args, 'hard_model', ALLOWED_MODELS[1]),
        threshold=getattr(args, 'routing_threshold', 4))
