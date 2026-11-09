import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.budget import BudgetManager
from src.domain import TaskSpec
from src.estimator import predict
from src.oj_adapter import OJAdapter
from src.telemetry import Recorder
from tools.live_evaluate import ContainerWorkers


class LiveController(unittest.TestCase):
    def test_missing_credentials_stops_before_docker(self):
        workers = ContainerWorkers(BudgetManager(100000), model='fixed')
        with patch.dict('os.environ', {'LLM_BASE_URL': '', 'LLM_API_KEY': ''}), \
             patch('tools.live_evaluate.subprocess.run', side_effect=AssertionError('Docker started')) as run:
            with self.assertRaises(ValueError):
                workers.command('model', {})
        run.assert_not_called()

    def test_model_worker_requires_reservation_and_never_puts_key_in_argv(self):
        budget = BudgetManager(100000)
        workers = ContainerWorkers(budget, model='fixed')
        arguments = dict(messages=[dict(role='user', content='question')], model='fixed',
                         max_tokens=32, temperature=0, timeout=60)
        with self.assertRaises(ValueError):
            asyncio.run(workers.invoke(**arguments))
        recorder = Recorder(io.StringIO())
        task = TaskSpec('sample', 'math', 'question', 1, 'exact_int', Path('/tmp/sample'), Path('/tmp/sample'))
        recorder.prediction('scope', predict(task))
        reply = json.dumps(dict(content='answer', usage_metadata=dict(input_tokens=10, output_tokens=2)))
        result = subprocess.CompletedProcess([], 0, stdout=reply, stderr='')
        with patch.dict('os.environ', {'LLM_BASE_URL': 'https://proxy.invalid/v1', 'LLM_API_KEY': 'synthetic-secret'}), \
             patch('tools.live_evaluate.subprocess.run', return_value=result) as run:
            adapter = OJAdapter(budget, recorder, model_name='fixed', model=workers)
            self.assertEqual(asyncio.run(adapter.invoke('scope', arguments['messages'], output_cap=32)), 'answer')
        command = run.call_args_list[0].args[0]
        self.assertNotIn('synthetic-secret', ' '.join(command))
        self.assertIn('LLM_API_KEY', command)
        payload = json.loads(run.call_args_list[0].kwargs['input'])
        self.assertGreater(payload['reservation_units'], 0)
        self.assertEqual(budget.actual, 30)
        self.assertEqual(budget.unresolved, 0)

    def test_verification_worker_has_no_network_or_credentials(self):
        workers = ContainerWorkers(BudgetManager(100000), model='fixed')
        result = subprocess.CompletedProcess([], 0,
            stdout=json.dumps(dict(passed=True, reason='passed', diagnostic='')), stderr='')
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('os.environ', {'LLM_BASE_URL': 'https://proxy.invalid', 'LLM_API_KEY': 'synthetic-secret'}), \
             patch('tools.live_evaluate.subprocess.run', return_value=result) as run:
            self.assertTrue(workers.verify(Path(directory), 'checks.py').passed)
        call = run.call_args_list[0]
        command = call.args[0]
        self.assertEqual(command[command.index('--network') + 1], 'none')
        self.assertNotIn('LLM_API_KEY', command)
        self.assertNotIn('LLM_API_KEY', call.kwargs['env'])
        self.assertTrue(any('dst=/input,readonly' in value for value in command))


if __name__ == '__main__':
    unittest.main()
