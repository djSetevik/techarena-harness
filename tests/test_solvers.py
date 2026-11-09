import asyncio
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from src.answer_writer import save_answer
from src.budget import BudgetManager, BudgetExceeded
from src.coding import contract, repair
from src.domain import TaskSpec, FeasibilityResult, Status
from src.estimator import predict
from src.model_solver import ModelSolver
from src.oj_adapter import OJAdapter
from src.scheduler import Candidate
from src.solvers import solve_math
from src.telemetry import Recorder
from src.verification import IsolatedRunner, Verification


class Solvers(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.root / 'task.json').write_text('{}')
        self.source = self.workspace / 'module.py'
        self.source.write_text('def value():\n    return 0\n')
        self.tests = self.workspace / 'checks.py'
        self.tests.write_bytes(b'# immutable test fixture, never executed on host\n')
        self.task = TaskSpec('any', 'coding', 'Run python3 checks.py. Fix the bugs in module.py. Do not edit tests.',
                             5, 'unittest', self.root, self.workspace)
        self.recorder = Recorder(io.StringIO())
        self.recorder.prediction(str(self.root), predict(self.task))
        self.budget = BudgetManager(1_000_000)

    def adapter(self, *texts, usage=True, calls=5):
        responses = [SimpleNamespace(content=text, usage_metadata=(dict(input_tokens=10,
            output_tokens=5, reasoning_tokens=2, cache_tokens=3) if usage else None)) for text in texts]
        self.handle = SimpleNamespace(invoke=AsyncMock(side_effect=responses))
        return OJAdapter(self.budget, self.recorder, model_name='fixed', model=self.handle, max_calls=calls)

    @staticmethod
    def fake_verifier(workspace, entry):
        # This fake describes the verification protocol; it does NOT execute
        # or claim to validate arbitrary Python semantics.
        passed = 'return 2' in (workspace / 'module.py').read_text()
        return Verification(passed, 'passed' if passed else 'tests_failed', 'synthetic mismatch')

    def test_C02_bad_patch_then_good_both_usage_recorded(self):
        original_tests = self.tests.read_bytes()
        adapter = self.adapter('def value():\n    return 1', 'def value():\n    return 2')
        answer = asyncio.run(repair(self.task, adapter, self.fake_verifier, self.recorder))
        self.assertEqual(answer, 'DONE')
        self.assertEqual(self.budget.actual, 120)
        self.assertEqual(self.tests.read_bytes(), original_tests)
        self.assertIn('return 2', self.source.read_text())
        self.assertFalse((self.root / 'answer.txt').exists())
        save_answer(self.root, answer)
        self.assertEqual((self.root / 'answer.txt').read_text().strip(), 'DONE')
        kwargs = self.handle.invoke.call_args.kwargs
        self.assertEqual(kwargs['model'], 'fixed')
        self.assertEqual(kwargs['max_tokens'], 2048)
        self.assertEqual(kwargs['timeout'], 60)

    def test_C03_compile_error_timeout_keep_original(self):
        original = self.source.read_bytes()
        for proposal, verifier in (('invalid python !', self.fake_verifier),
                                    ('def value():\n    return 2',
                                     lambda w, e: Verification(False, 'timeout'))):
            # First verification must fail normally so a model attempt occurs.
            count = []
            def verify(workspace, entry):
                count.append(1)
                return Verification(False, 'tests_failed') if len(count) == 1 else verifier(workspace, entry)
            adapter = self.adapter(proposal)
            answer = asyncio.run(repair(self.task, adapter, verify, self.recorder, max_attempts=1))
            self.assertIsNone(answer)
            self.assertEqual(self.source.read_bytes(), original)
            self.assertFalse((self.root / 'answer.txt').exists())

    def test_C04_C05_paths_and_mutation_rejected(self):
        for name in ('../outside.py', '/outside.py', 'test_module.py', '.hidden.py'):
            with self.assertRaises(ValueError):
                contract(f'Run python3 checks.py. Fix the bugs in {name}.')
        outside = self.root / 'outside.py'
        outside.write_text('original')
        self.source.unlink()
        self.source.symlink_to(outside)
        with self.assertRaises(ValueError):
            asyncio.run(repair(self.task, None, self.fake_verifier, self.recorder, max_attempts=0))
        self.source.unlink()
        self.source.write_text('def value():\n    return 0\n')
        original_tests = self.tests.read_bytes()
        def mutating_verifier(workspace, entry):
            (workspace / entry).write_text('modified tests')
            return Verification(True, 'passed')
        self.assertIsNone(asyncio.run(repair(self.task, None, mutating_verifier, self.recorder, max_attempts=0)))
        self.assertEqual(self.tests.read_bytes(), original_tests)
        self.assertIn('return 0', self.source.read_text())

    def test_original_passes_without_model_or_budget(self):
        self.source.write_text('def value():\n    return 2\n')
        before = self.source.read_bytes()
        self.assertEqual(asyncio.run(repair(self.task, None, self.fake_verifier,
                                           self.recorder, max_attempts=0)), 'DONE')
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.budget.actual, 0)

    def test_C06_root_and_unisolated_refused(self):
        with patch('src.verification.os.geteuid', return_value=0):
            with self.assertRaises(ValueError):
                IsolatedRunner(isolated=True)
        with patch('src.verification.os.geteuid', return_value=1000):
            with self.assertRaises(ValueError):
                IsolatedRunner()

    def test_C06_subprocess_configuration_fake_only(self):
        from unittest.mock import MagicMock
        process = MagicMock(pid=12345, returncode=0)
        def launch(*args, **kwargs):
            kwargs['stdout'].write(b'x' * 100000)
            return process
        with patch('src.verification.os.geteuid', return_value=1000), \
             patch('src.verification.subprocess.Popen', side_effect=launch) as popen, \
             patch('src.verification.os.killpg') as kill, \
             patch.dict('os.environ', {'LLM_API_KEY': 'synthetic-secret', 'SSH_AUTH_SOCK': 'synthetic-sock'}):
            result = IsolatedRunner(isolated=True)(self.workspace, 'checks.py')
        self.assertTrue(result.passed)
        kwargs = popen.call_args.kwargs
        self.assertNotIn('LLM_API_KEY', kwargs['env'])
        self.assertNotIn('SSH_AUTH_SOCK', kwargs['env'])
        self.assertEqual(process.wait.call_args_list[0].kwargs['timeout'], 15)
        self.assertEqual(len(result.diagnostic), 4096)
        self.assertTrue(kwargs['start_new_session'])
        self.assertTrue(callable(kwargs['preexec_fn']))
        kill.assert_called_once()

    def test_adapter_usage_before_invalid_answer_and_global_call_cap(self):
        adapter = self.adapter('not json', calls=1)
        task = replace(self.task, task_type='math', check='exact_int', instruction='unknown math')
        solver = ModelSolver(adapter, self.recorder)
        with self.assertRaises(ValueError):
            asyncio.run(solver(Candidate(task, FeasibilityResult(Status.UNKNOWN, 'test'), predict(task)), self.budget))
        self.assertEqual(self.budget.actual, 60)
        with self.assertRaises(BudgetExceeded):
            asyncio.run(adapter.invoke(str(self.root), [], output_cap=1))
        self.assertEqual(self.handle.invoke.await_count, 1)

    def test_missing_usage_retains_reserve(self):
        adapter = self.adapter('answer', usage=False)
        self.assertEqual(asyncio.run(adapter.invoke(str(self.root), [], output_cap=10)), 'answer')
        self.assertGreater(self.budget.unresolved, 0)
        self.assertTrue(self.budget.closed)

    def test_cli_runtime_fake_model_path_no_expected_in_prompt(self):
        import run_agent
        tasks = self.root / 'batch'
        directory = tasks / 'renamed'
        directory.mkdir(parents=True)
        (directory / 'task.json').write_text(json.dumps(dict(task_type='math',
            instruction='Find the seventh term of the specified recurrence: 1, 1, next is sum of previous two.',
            reward=3, check='exact_int', expected='fake-label-do-not-send')))
        recorder = Recorder(io.StringIO())
        handle = SimpleNamespace(invoke=AsyncMock(return_value=SimpleNamespace(
            content='{"sufficient":true,"answer":"13"}',
            usage_metadata=dict(input_tokens=10, output_tokens=5))))
        adapter = OJAdapter(self.budget, recorder, model_name='fixed', model=handle)
        with patch('socket.socket.connect', side_effect=AssertionError('network')), \
             patch('src.verification.subprocess.Popen', side_effect=AssertionError('task code')):
            self.assertEqual(run_agent.run(SimpleNamespace(tasks_dir=tasks, max_llm_calls=1),
                             self.budget, recorder, adapter=adapter), 0)
        self.assertEqual((directory / 'answer.txt').read_text().strip(), '13')
        self.assertNotIn('fake-label-do-not-send', json.dumps(handle.invoke.call_args.kwargs))
        events = [json.loads(line) for line in recorder.stream.getvalue().splitlines()]
        self.assertEqual(events[0]['event'], 'task_prediction')
        self.assertLess([e['event'] for e in events].index('llm_usage'),
                        [e['event'] for e in events].index('answer_saved'))

    def test_F15_unknown_math_operation_not_partially_solved(self):
        prefix = 'A warehouse starts with 20 boxes. '
        target = 'How many boxes does it have at the end?'
        self.assertEqual(solve_math(prefix + 'It ships 2 boxes per day for 3 days. ' + target), '14')
        self.assertIsNone(solve_math(prefix + 'It ships 2 boxes per day for 3 days. The stock is halved. ' + target))
        self.assertIsNone(solve_math(prefix + 'Then the stock is split equally into 0 warehouses and it keeps one share (rounded down). ' + target))

    @unittest.skipUnless(importlib.util.find_spec('openjiuwen'), 'NOT RUN: SDK not installed; installation requires permission')
    def test_C01_real_sdk_model_invoke_with_fake_client(self):
        # Real Model.invoke execution, fake lowest transport boundary, no proxy.
        from src.oj_adapter import sdk_model, configure_sdk_logging
        configure_sdk_logging()
        invoke = AsyncMock(return_value=SimpleNamespace(content='ok'))
        lower = SimpleNamespace(invoke=invoke,
                                stream=AsyncMock())
        with patch('openjiuwen.core.foundation.llm.model.create_model_client', return_value=lower), \
             patch('socket.create_connection', side_effect=AssertionError('network')):
            model = sdk_model(model_name='fixed', api_base='https://proxy.invalid/v1',
                              api_key='synthetic', timeout=2)
            response = asyncio.run(model.invoke(messages=[dict(role='user', content='offline')],
                                               model='fixed', max_tokens=1, timeout=2))
        self.assertEqual(response.content, 'ok')
        invoke.assert_awaited_once()

    @unittest.skipUnless(importlib.util.find_spec('openjiuwen'), 'NOT RUN: SDK not installed in this interpreter')
    def test_C01_real_sdk_provider_usage_and_retries_fake_transport(self):
        from src.oj_adapter import sdk_model, configure_sdk_logging
        configure_sdk_logging()
        response = SimpleNamespace(id='offline', model='fixed', usage=SimpleNamespace(
            prompt_tokens=2000, completion_tokens=500, total_tokens=2500,
            prompt_tokens_details=SimpleNamespace(cached_tokens=1000),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=100)),
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
                content='2', tool_calls=None, reasoning_content=None))])
        create = AsyncMock(return_value=response)
        transport = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                    close=AsyncMock())
        with patch('openai.AsyncOpenAI', return_value=transport) as factory, \
             patch('socket.socket.connect', side_effect=AssertionError('network')):
            model = sdk_model(model_name='fixed', api_base='https://proxy.invalid/v1',
                              api_key='synthetic', timeout=2)
            adapter = OJAdapter(self.budget, self.recorder, model_name='fixed', model=model)
            async def invoke():
                try:
                    return await adapter.invoke(str(self.root), [dict(role='user', content='Return 2.')], output_cap=512)
                finally:
                    await type(model._client).aclose()
            self.assertEqual(asyncio.run(invoke()), '2')
        self.assertEqual(self.budget.actual, 7000)
        self.assertEqual(self.budget.unresolved, 0)
        create.assert_awaited_once()
        self.assertEqual(factory.call_args.kwargs['max_retries'], 0)
        self.assertEqual(create.call_args.kwargs['model'], 'fixed')
        self.assertEqual(create.call_args.kwargs['max_tokens'], 512)

    @unittest.skipUnless(importlib.util.find_spec('openjiuwen'), 'NOT RUN: SDK not installed in this interpreter')
    def test_real_sdk_timeout_has_one_transport_attempt_and_unresolved_usage(self):
        from src.oj_adapter import sdk_model, configure_sdk_logging
        configure_sdk_logging()
        create = AsyncMock(side_effect=TimeoutError('synthetic transport timeout'))
        transport = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                    close=AsyncMock())
        with patch('openai.AsyncOpenAI', return_value=transport), \
             patch('socket.socket.connect', side_effect=AssertionError('network')):
            model = sdk_model(model_name='fixed', api_base='https://proxy.invalid/v1',
                              api_key='synthetic', timeout=2)
            adapter = OJAdapter(self.budget, self.recorder, model_name='fixed', model=model)
            async def invoke():
                try:
                    return await adapter.invoke(str(self.root), [dict(role='user', content='offline')], output_cap=16)
                finally:
                    await type(model._client).aclose()
            with self.assertRaises(Exception):
                asyncio.run(invoke())
        create.assert_awaited_once()
        self.assertEqual(self.budget.actual, 0)
        self.assertGreater(self.budget.unresolved, 0)
        self.assertTrue(self.budget.closed)


if __name__ == '__main__':
    unittest.main()
