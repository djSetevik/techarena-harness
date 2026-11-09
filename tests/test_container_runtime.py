"""Real task execution only in an explicitly enabled, non-root test container."""
import asyncio
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.answer_writer import save_answer
from src.budget import BudgetManager
from src.coding import repair
from src.domain import TaskSpec
from src.estimator import predict
from src.oj_adapter import OJAdapter
from src.telemetry import Recorder
from src.verification import IsolatedRunner


@unittest.skipUnless(os.getenv('TECHARENA_CONTAINER_TESTS') == '1' and os.geteuid() != 0,
                     'Requires explicitly enabled isolated non-root container')
class ContainerRuntime(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.root / 'task.json').write_text('{}')
        self.source = self.workspace / 'module.py'
        self.source.write_text('def add(a, b):\n    return a-b\n')
        self.tests = self.workspace / 'checks.py'
        self.tests.write_text('from module import add\nassert add(2,3)==5\nassert add(-4,4)==0\nassert add(0,0)==0\n')
        self.task = TaskSpec('synthetic', 'coding', 'Run python3 checks.py. Fix the bugs in module.py.',
                             1, 'unittest', self.root, self.workspace)
        self.recorder = Recorder(io.StringIO())
        self.recorder.prediction(str(self.root), predict(self.task))

    def test_C02_actual_tests_two_patches_and_commit(self):
        before = self.tests.read_bytes()
        budget = BudgetManager(100000)
        handle = SimpleNamespace(invoke=AsyncMock(side_effect=[
            SimpleNamespace(content=code, usage_metadata=dict(input_tokens=10, output_tokens=5))
            for code in ('def add(a,b):\n    return a*b', 'def add(a,b):\n    return a+b')]))
        adapter = OJAdapter(budget, self.recorder, model_name='fake', model=handle)
        answer = asyncio.run(repair(self.task, adapter, IsolatedRunner(isolated=True), self.recorder))
        self.assertEqual(answer, 'DONE')
        self.assertEqual(budget.actual, 120)
        self.assertEqual(handle.invoke.await_count, 2)
        self.assertEqual(self.tests.read_bytes(), before)
        self.assertIn('a+b', self.source.read_text())
        save_answer(self.root, answer)
        self.assertEqual((self.root / 'answer.txt').stat().st_mode & 0o777, 0o644)

    def test_C03_real_timeout_preserves_original(self):
        self.tests.write_text('import time\ntime.sleep(5)\n')
        before = self.source.read_bytes()
        answer = asyncio.run(repair(self.task, None, IsolatedRunner(isolated=True, timeout=1),
                                   self.recorder, max_attempts=0))
        self.assertIsNone(answer)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((self.root / 'answer.txt').exists())

    def test_C06_real_subprocess_environment_is_clean(self):
        self.tests.write_text('import os\nassert "LLM_API_KEY" not in os.environ\n'
                              'assert "SSH_AUTH_SOCK" not in os.environ\n'
                              'assert "PYTHONPATH" not in os.environ\n')
        with patch.dict('os.environ', {'LLM_API_KEY': 'synthetic', 'SSH_AUTH_SOCK': 'synthetic'}):
            result = IsolatedRunner(isolated=True)(self.workspace, 'checks.py')
        self.assertTrue(result.passed, result.reason)

    def test_C06_real_output_limit(self):
        self.tests.write_text('print("x" * 1000000)\n')
        result = IsolatedRunner(isolated=True, output_bytes=8192)(self.workspace, 'checks.py')
        self.assertFalse(result.passed)
        self.assertLessEqual(len(result.diagnostic), 4096)


if __name__ == '__main__':
    unittest.main()
