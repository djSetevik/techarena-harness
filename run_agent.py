"""TechArena harness: bounded offline solving followed by paid scheduling."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from src.task_loader import load_task
from src.answer_writer import save_answer
from src.feasibility import detect
from src.domain import Status, FeasibilityResult
from src.budget import BudgetManager, limit_units
from src.estimator import predict
from src.telemetry import Recorder
from src.scheduler import Candidate, select
from src.oj_adapter import OJAdapter
from src.model_solver import ModelSolver
from src.model_routing import ALLOWED_MODELS, add_arguments as add_routing_arguments, from_arguments as routing_from_arguments
from src.coding import repair
from src.verification import IsolatedRunner

LOG = logging.getLogger('techarena')


class StopRequested(BaseException):
    def __init__(self, signum):
        self.signum = signum


def stop(signum, frame):
    raise StopRequested(signum)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks-dir', required=True, type=Path)
    parser.add_argument('--max-llm-calls', type=int, default=int(os.getenv('MAX_LLM_CALLS','3')))
    parser.add_argument('--metrics-path', type=Path)
    parser.add_argument('--enable-llm', action='store_true', help='Explicitly enable paid proxy requests')
    parser.add_argument('--model', default=os.getenv('LLM_MODEL'))
    add_routing_arguments(parser)
    parser.add_argument('--reasoning-usage', choices=['included', 'separate'])
    parser.add_argument('--isolated-coding', action='store_true',
                        help='Operator confirms isolated container, secrets/mount/network policy')
    parser.add_argument('--offline-ablation', choices=['full', 'no_gate', 'no_deterministic'], default='full',
                        help='Development comparison only; incompatible with paid execution')
    args = parser.parse_args()
    try:
        policy = routing_from_arguments(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.model_mode == 'complexity' and args.model:
        parser.error('--model/LLM_MODEL is fixed-mode only; use --easy-model/--hard-model for routing')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if not args.tasks_dir.is_dir():
        parser.error(f'Tasks directory not found: {args.tasks_dir}')
    try:
        budget = BudgetManager(limit_units(os.getenv('BUDGET'), offline=not args.enable_llm))
    except ValueError as exc:
        parser.error(str(exc))
    if args.max_llm_calls < 0:
        parser.error('--max-llm-calls must be nonnegative')
    if args.offline_ablation != 'full' and (args.enable_llm or args.isolated_coding):
        parser.error('Ablations require offline execution without coding subprocesses')
    with ExitStack() as stack:
        stream = None
        if args.metrics_path:
            target = args.metrics_path.resolve()
            if target.is_relative_to(args.tasks_dir.resolve()) or target.is_relative_to(Path(__file__).resolve().parent):
                parser.error('Metrics must be outside runtime source and task directories')
            stream = stack.enter_context(target.open('x', encoding='utf-8'))
        recorder = Recorder(stream)
        verifier = None
        if args.isolated_coding:
            try:
                verifier = IsolatedRunner(isolated=True)
            except ValueError as exc:
                parser.error(str(exc))
        adapter = None
        args.adapter_missing_reason = 'adapter_unavailable'
        if args.enable_llm:
            if (args.model_mode == 'fixed' and args.model not in ALLOWED_MODELS) or args.reasoning_usage is None:
                parser.error('Live requires an explicit Q1 model and confirmed --reasoning-usage')
            if budget.limit and args.max_llm_calls:
                base, key = os.getenv('LLM_BASE_URL'), os.getenv('LLM_API_KEY')
                if not base or not key:
                    args.adapter_missing_reason = 'credentials'
                else:
                    try:
                        adapter = OJAdapter(budget, recorder, model_name=policy.primary_model,
                            allowed_models=policy.allowed_models,
                            api_base=base, api_key=key,
                            reasoning_in_output=args.reasoning_usage == 'included',
                            max_calls=args.max_llm_calls)
                    except Exception as exc:
                        args.adapter_missing_reason = 'sdk_unavailable' if isinstance(exc, ImportError) else 'model_configuration'
                if adapter is None:
                    recorder.emit('model_disabled', 'run', skip_reason=args.adapter_missing_reason)
        previous = signal.signal(signal.SIGTERM, stop)
        stack.callback(signal.signal, signal.SIGTERM, previous)
        try:
            return run(args, budget, recorder, adapter=adapter, verifier=verifier)
        except (StopRequested, KeyboardInterrupt) as exc:
            recorder.emit('run_interrupted', 'run', **budget.snapshot())
            return 128 + (exc.signum if isinstance(exc, StopRequested) else signal.SIGINT)


def run(args, budget, recorder, *, adapter=None, verifier=None):
    ablation = getattr(args, 'offline_ablation', 'full')
    if ablation != 'full' and (adapter is not None or verifier is not None):
        raise ValueError('Ablations cannot execute models or task programs')
    policy = None
    if getattr(args, 'model_mode', 'fixed') == 'complexity':
        policy = routing_from_arguments(args)
        if adapter is not None and not policy.allowed_models <= adapter.allowed_models:
            raise ValueError('Routing profile exceeds adapter model allowlist')
    tasks = []
    for path in args.tasks_dir.glob('*/task.json'):
        try:
            tasks.append(load_task(path, args.tasks_dir))
        except (OSError, ValueError) as exc:
            LOG.warning('Cannot load %s: %s', path, exc)

    # Persist every original forecast before any detector/solver attempt.
    for task in tasks:
        recorder.prediction(str(task.task_dir), predict(task))
    cost_rank = {'math': 0, 'data_analysis': 1, 'search': 2, 'coding': 3}
    tasks.sort(key=lambda task: (cost_rank.get(task.task_type, 4), -task.reward))
    solved = 0
    reward = 0
    start = time.monotonic()
    pending = []
    for task in tasks:
        scope = str(task.task_dir)
        try:
            existing = task.task_dir / 'answer.txt'
            if existing.exists() or existing.is_symlink():
                recorder.emit('task_end', scope, skip_reason='existing_answer')
                continue
            feasibility = detect(task)
            recorder.emit('feasibility', scope, status=feasibility.status.value,
                          reason_code=feasibility.reason_code, scope_complete=feasibility.scope_complete)
            LOG.info('%s feasibility=%s reason=%s scope_complete=%s', task.task_id,
                     feasibility.status.value, feasibility.reason_code, feasibility.scope_complete)
            if feasibility.status == Status.UNSOLVABLE and ablation != 'no_gate':
                LOG.info('%s evidence=%s', task.task_id, feasibility.evidence)
                recorder.emit('task_end', scope, skip_reason='proven_unsolvable')
                continue
            if ablation == 'no_gate' and feasibility.status == Status.UNSOLVABLE:
                feasibility = FeasibilityResult(Status.UNKNOWN, 'OFFLINE_GATE_ABLATION')
            if task.task_type in {'search', 'data_analysis', 'math'}:
                result = feasibility.answer
            else:
                result = None
                if verifier is not None and task.workspace != task.task_dir:
                    result = asyncio.run(repair(task, None, verifier, recorder, max_attempts=0))
            if ablation == 'no_deterministic':
                result = None
            if result is None:
                LOG.info('%s unresolved', task.task_id)
                pending.append(Candidate(task, feasibility, recorder.initial(scope)))
                continue
            save_answer(task.task_dir, result)
            solved += 1
            reward += task.reward
            recorder.emit('answer_saved', scope, method='deterministic')
            LOG.info('%s saved (reward=%s)', task.task_id, task.reward)
        except Exception as exc:
            LOG.warning('%s failed (%s)', task.task_id, type(exc).__name__)
            recorder.emit('task_end', scope, skip_reason='local_error')
    solver = ModelSolver(adapter, recorder, verifier=verifier, routing=policy) if adapter is not None else None
    if solver is None:
        list(select(pending, budget, None, recorder, max_calls=args.max_llm_calls,
                    adapter_missing_reason=getattr(args, 'adapter_missing_reason', 'adapter_unavailable')))
    else:
        async def paid():
            nonlocal solved, reward
            for candidate in select(pending, budget, solver, recorder, max_calls=args.max_llm_calls):
                scope = str(candidate.task.task_dir)
                if candidate.task.task_type == 'coding' and verifier is None:
                    recorder.emit('task_end', scope, skip_reason='isolation')
                    continue
                try:
                    answer = await solver(candidate, budget)
                    if answer is not None:
                        save_answer(candidate.task.task_dir, answer)
                        solved += 1
                        reward += candidate.task.reward
                        recorder.emit('answer_saved', scope, method='model_format_checked')
                    else:
                        recorder.emit('task_end', scope, skip_reason='unresolved')
                except Exception as exc:
                    recorder.emit('task_end', scope, skip_reason='model_or_verification_error',
                                  error_type=type(exc).__name__)
        asyncio.run(paid())
    recorder.emit('budget_summary', 'run', **budget.snapshot())
    LOG.info('Completed: %s/%s tasks, claimed reward %.1f, elapsed %.1fs', solved,
             len(tasks), reward, time.monotonic() - start)
    # Claims are local heuristics, only the hidden evaluator confirms points.
    return 0


if __name__ == '__main__':
    sys.exit(main())
