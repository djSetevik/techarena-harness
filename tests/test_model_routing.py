import asyncio
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from src.budget import BudgetManager, BudgetExceeded
from src.domain import TaskSpec, FeasibilityResult, Status
from src.estimator import predict
from src.model_routing import ALLOWED_MODELS, ModelRouting, features
from src.model_solver import ModelSolver
from src.oj_adapter import OJAdapter
from src.scheduler import Candidate
from src.telemetry import Recorder
from src.verification import Verification


EASY, HARD = ALLOWED_MODELS


def response(text='answer', usage=True):
    return SimpleNamespace(content=text, usage_metadata=dict(input_tokens=10, output_tokens=2) if usage else None)


class Routing(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.recorder = Recorder(io.StringIO())
        self.budget = BudgetManager(1000000)
        self.handles = {name: SimpleNamespace(invoke=AsyncMock(return_value=response())) for name in ALLOWED_MODELS}
        self.factory_calls = []
        def factory(name):
            self.factory_calls.append(name)
            return self.handles[name]
        self.adapter = OJAdapter(self.budget, self.recorder, model_name=EASY,
            model=self.handles[EASY], model_factory=factory, allowed_models=ALLOWED_MODELS, max_calls=4)

    def task(self, name='task', instruction='A week has seven days. How many days are in two weeks?', kind='math'):
        directory = self.root / name
        directory.mkdir(exist_ok=True)
        task = TaskSpec(name, kind, instruction, 1, 'exact_int', directory, directory / 'workspace')
        self.recorder.prediction(str(directory), predict(task))
        return task

    def selected(self):
        return [json.loads(line) for line in self.recorder.stream.getvalue().splitlines()
                if json.loads(line)['event'] == 'model_selected']

    def test_simple_and_complex_use_different_models_without_classifier_calls(self):
        policy = ModelRouting(mode='complexity')
        easy = self.task('simple')
        hard = self.task('complex', 'Evaluate (2+3)*(7-4)+8*2-9/3.')
        bound = [policy.bind(task, self.adapter, self.recorder) for task in (easy, hard)]
        self.assertEqual(self.adapter.calls, 0)
        self.assertEqual(sum(handle.invoke.await_count for handle in self.handles.values()), 0)
        async def run():
            for task, model in zip((easy, hard), bound):
                await model.invoke(str(task.task_dir), [], output_cap=32)
        asyncio.run(run())
        self.assertEqual([event['model'] for event in self.selected()], [EASY, HARD])
        self.assertEqual(self.handles[EASY].invoke.call_args.kwargs['model'], EASY)
        self.assertEqual(self.handles[HARD].invoke.call_args.kwargs['model'], HARD)
        self.assertEqual(self.budget.actual, 60)
        self.assertEqual(self.adapter.calls, 2)
        self.assertEqual(self.factory_calls, [HARD])

    def test_coding_structure_not_just_length(self):
        task = self.task(kind='coding', instruction='Run python3 checks.py. Fix the bugs in module.py.')
        task.workspace.mkdir()
        (task.workspace / 'module.py').write_text('def f(x):\n if x:\n  for y in x:\n   if y:\n    while y:\n     y-=1\n return x\n')
        (task.workspace / 'checks.py').write_text('# tests')
        value = features(task)
        self.assertLess(value.context_bytes, 8192)
        self.assertEqual(value.branches, 4)
        self.assertEqual(value.control_depth, 4)
        bound = ModelRouting(mode='complexity').bind(task, self.adapter, self.recorder)
        asyncio.run(bound.invoke(str(task.task_dir), [], output_cap=32))
        self.assertEqual(self.selected()[0]['model'], HARD)

    def test_no_id_reward_expected_or_row_count_features(self):
        task = self.task()
        self.assertEqual(features(task), features(replace(task, task_id='changed', reward=999)))
        keys = set(asdict(features(task)))
        self.assertTrue(keys.isdisjoint({'task_id', 'expected', 'reward', 'rows', 'line_count'}))

    def test_unknown_features_use_configured_profile_not_unsolvable(self):
        task = self.task(kind='coding', instruction='An unsupported coding contract.')
        bound = ModelRouting(mode='complexity').bind(task, self.adapter, self.recorder)
        asyncio.run(bound.invoke(str(task.task_dir), [], output_cap=32))
        self.assertEqual(self.selected()[0]['model'], HARD)
        self.assertEqual(self.selected()[0]['complexity'], 'unknown')

    def test_global_call_cap_cannot_reset_on_model_switch(self):
        self.adapter.max_calls = 1
        task = self.task()
        asyncio.run(self.adapter.invoke(str(task.task_dir), [], output_cap=32, model_name=EASY))
        with self.assertRaises(BudgetExceeded):
            asyncio.run(self.adapter.invoke(str(task.task_dir), [], output_cap=32, model_name=HARD))
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(self.budget.actual, 30)
        self.assertEqual(self.factory_calls, [])

    def test_fixed_adapter_rejects_override_before_paid_request(self):
        task = self.task()
        fixed = OJAdapter(self.budget, self.recorder, model_name=EASY, model=self.handles[EASY])
        with self.assertRaises(ValueError):
            asyncio.run(fixed.invoke(str(task.task_dir), [], output_cap=32, model_name=HARD))
        with self.assertRaises(ValueError):
            ModelRouting(mode='complexity').bind(task, fixed, self.recorder)
        self.assertEqual(fixed.calls, 0)
        self.assertEqual(self.budget.actual, 0)

    def test_zero_or_unknown_budget_does_not_fallback_to_other_model(self):
        task = self.task()
        self.budget.limit = 0
        with self.assertRaises(BudgetExceeded):
            asyncio.run(ModelRouting(mode='complexity').bind(task, self.adapter, self.recorder).invoke(str(task.task_dir), [], output_cap=32))
        self.assertEqual(self.adapter.calls, 0)
        self.budget.limit = 1000000
        self.handles[EASY].invoke.return_value = response(usage=False)
        asyncio.run(self.adapter.invoke(str(task.task_dir), [], output_cap=32))
        self.assertTrue(self.budget.closed)
        with self.assertRaises(BudgetExceeded):
            asyncio.run(self.adapter.invoke(str(task.task_dir), [], output_cap=32, model_name=HARD))
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(self.handles[HARD].invoke.await_count, 0)

    def test_task_scope_cannot_reuse_another_tasks_route(self):
        task = self.task()
        bound = ModelRouting(mode='complexity').bind(task, self.adapter, self.recorder)
        with self.assertRaises(ValueError):
            asyncio.run(bound.invoke(str(self.root / 'other'), [], output_cap=32))
        self.assertEqual(self.adapter.calls, 0)

    def test_failed_coding_patch_escalates_but_fixed_mode_does_not(self):
        for mode in ('complexity', 'fixed'):
            with self.subTest(mode=mode):
                self.setUp()
                task = self.task(kind='coding', instruction='Run python3 checks.py. Fix the bugs in module.py.')
                task.workspace.mkdir()
                (task.workspace / 'module.py').write_text('def add(a,b):\n return a-b\n')
                tests = task.workspace / 'checks.py'
                tests.write_text('# immutable synthetic verification contract')
                before = tests.read_bytes()
                bad, good = response('def add(a,b):\n return a*b'), response('def add(a,b):\n return a+b')
                if mode == 'fixed':
                    self.handles[EASY].invoke.side_effect = [bad, good]
                else:
                    self.handles[EASY].invoke.return_value = bad
                    self.handles[HARD].invoke.return_value = good
                def verify(workspace, entry):
                    passed = 'return a+b' in (workspace / 'module.py').read_text()
                    return Verification(passed, 'passed' if passed else 'tests_failed')
                solver = ModelSolver(self.adapter, self.recorder, verifier=verify,
                                     routing=ModelRouting(mode=mode))
                candidate = Candidate(task, FeasibilityResult(Status.UNKNOWN, 'test'), predict(task))
                self.assertEqual(asyncio.run(solver(candidate, self.budget)), 'DONE')
                self.assertEqual([event['model'] for event in self.selected()], [EASY, HARD if mode == 'complexity' else EASY])
                self.assertEqual(self.budget.actual, 60)
                self.assertEqual(tests.read_bytes(), before)

    def test_runtime_routes_unknown_tasks_but_skips_proven_impossible(self):
        import run_agent
        tasks = self.root / 'batch'
        for name, instruction in (('easy', 'A week has seven days. How many days are in two weeks?'),
                                  ('hard', 'Evaluate (2+3)*(7-4)+8*2-9/3.'),
                                  ('impossible', 'Let x be an arbitrary integer. Evaluate x*2.')):
            directory = tasks / name
            directory.mkdir(parents=True)
            (directory / 'task.json').write_text(json.dumps(dict(task_type='math', instruction=instruction,
                reward=999 if name == 'impossible' else 1, check='exact_int', expected='fake-do-not-send')))
        self.handles[EASY].invoke.return_value = response('{"sufficient":true,"answer":"14"}')
        self.handles[HARD].invoke.return_value = response('{"sufficient":true,"answer":"28"}')
        run_agent.run(SimpleNamespace(tasks_dir=tasks, max_llm_calls=2, model_mode='complexity'),
                      self.budget, self.recorder, adapter=self.adapter)
        self.assertEqual(self.adapter.calls, 2)
        self.assertCountEqual([event['model'] for event in self.selected()], [EASY, HARD])
        self.assertFalse((tasks / 'impossible/answer.txt').exists())
        self.assertEqual((tasks / 'easy/answer.txt').read_text().strip(), '14')
        self.assertEqual((tasks / 'hard/answer.txt').read_text().strip(), '28')
        for handle in self.handles.values():
            self.assertNotIn('fake-do-not-send', str(handle.invoke.call_args))

    def test_profiles_and_threshold_are_configurable_and_validated(self):
        task = self.task()
        bound = ModelRouting(mode='complexity', easy_model=HARD, hard_model=EASY).bind(task, self.adapter, self.recorder)
        asyncio.run(bound.invoke(str(task.task_dir), [], output_cap=32))
        self.assertEqual(self.selected()[0]['model'], HARD)
        with self.assertRaises(ValueError):
            ModelRouting(threshold=0)
        with self.assertRaises(ValueError):
            ModelRouting(easy_model='unapproved-provider-model')


if __name__ == '__main__':
    unittest.main()
