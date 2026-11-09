import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.budget import BudgetExceeded, BudgetManager, ProxyExhausted, Usage, limit_units, normalize_usage
from src.domain import TaskSpec, Status, FeasibilityResult
from src.estimator import predict, Prediction
from src.scheduler import Candidate, run_paid
from src.telemetry import Recorder


def task(name='a', reward=1):
    return TaskSpec(name, 'search', 'question', reward, 'exact_str', Path('/tmp') / name, Path('/tmp') / name)


class BudgetTests(unittest.TestCase):
    def test_B01_B02_B03_usage(self):
        raw = dict(prompt_tokens=2000, completion_tokens=500,
                   completion_tokens_details={'reasoning_tokens': 100},
                   prompt_tokens_details={'cached_tokens': 1000})
        self.assertEqual(normalize_usage(raw, reasoning_in_output=True).units, 7000)
        self.assertEqual(normalize_usage(raw, reasoning_in_output=False).units, 8000)
        self.assertEqual(Usage(1, 0).units, 1)
        self.assertEqual(limit_units('700.1'), 7001)

    def test_B05_invalid_budget(self):
        for value in ('', '-1', 'NaN', 'Infinity', 'abc', '0.01'):
            with self.assertRaises(ValueError):
                limit_units(value)
        with self.assertRaises(ValueError):
            limit_units(None)
        self.assertEqual(limit_units(None, offline=True), 0)

    def test_B06_concurrent_reservations(self):
        budget = BudgetManager(100)
        def reserve(_):
            try:
                return budget.reserve(60)
            except BudgetExceeded:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            tickets = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(t is not None for t in tickets), 1)
        ticket = next(t for t in tickets if t is not None)
        budget.finish(ticket)  # cancelled before sending: refund once
        self.assertEqual(budget.snapshot()['available_units'], 100)
        with self.assertRaises(KeyError):
            budget.finish(ticket)

    def test_B07_B09_B10_timeout_exhaustion_no_retry(self):
        for exception in (TimeoutError(), ProxyExhausted()):
            budget, calls = BudgetManager(100), []
            async def request():
                calls.append(1)
                raise exception
            with self.assertRaises(type(exception)):
                asyncio.run(budget.execute(60, request, lambda r: r))
            self.assertEqual(len(calls), 1)
            self.assertEqual(budget.unresolved, 60)
            self.assertEqual(budget.snapshot()['reserved_units'], 0)
            with self.assertRaises(BudgetExceeded):
                budget.reserve(1)

    def test_B08_usage_settled_before_response_processing(self):
        budget = BudgetManager(100)
        async def request():
            return {'usage': Usage(3, 2), 'text': 'invalid JSON'}
        response = asyncio.run(budget.execute(60, request, lambda r: r['usage']))
        with self.assertRaises(ValueError):
            json.loads(response['text'])
        self.assertEqual(budget.actual, 23)
        self.assertEqual(budget.unresolved, 0)

    def test_B11_absent_or_malformed_usage(self):
        for usage_of in (lambda r: None, lambda r: normalize_usage({}, reasoning_in_output=True)):
            budget = BudgetManager(100)
            async def request():
                return {}
            try:
                asyncio.run(budget.execute(60, request, usage_of))
            except KeyError:
                pass
            self.assertEqual(budget.unresolved, 60)
            self.assertTrue(budget.closed)

    def test_cancellation_after_send(self):
        budget = BudgetManager(100)
        async def scenario():
            started = asyncio.Event()
            async def request():
                started.set()
                await asyncio.Event().wait()
            future = asyncio.create_task(budget.execute(60, request, lambda r: None))
            await started.wait()
            future.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await future
        asyncio.run(scenario())
        self.assertEqual(budget.unresolved, 60)
        self.assertEqual(budget.snapshot()['reserved_units'], 0)

    def test_explicit_retry_needs_second_reservation(self):
        budget = BudgetManager(100)
        async def request():
            return Usage(1, 2)
        for _ in range(2):
            asyncio.run(budget.execute(40, request, lambda r: r))
        self.assertEqual(budget.actual, 42)

    def test_underreservation_is_recorded_and_stops_new_calls(self):
        budget = BudgetManager(100)
        async def request():
            return Usage(1, 20)
        asyncio.run(budget.execute(40, request, lambda r: r))
        self.assertEqual(budget.actual, 201)
        self.assertTrue(budget.closed)

    def test_B12_prediction_immutable_and_independent(self):
        original = task()
        prediction = predict(original)
        self.assertEqual(prediction, predict(replace(original, task_id='other', reward=999)))
        with self.assertRaises(FrozenInstanceError):
            prediction.expected_units = 0
        recorder = Recorder(io.StringIO())
        recorder.prediction('scope', prediction)
        recorder.emit('reestimate', 'scope', expected_units=1)
        self.assertEqual(recorder.initial('scope'), prediction)
        with self.assertRaises(ValueError):
            recorder.prediction('scope', prediction)

    def test_B13_B14_B15_scheduler(self):
        budget = BudgetManager(100)
        stream = io.StringIO()
        recorder = Recorder(stream)
        forecast = Prediction('search', 8, 20, 40, 3)
        candidates = []
        for name, reward, status in (('low', 1, Status.UNKNOWN), ('high', 9, Status.UNKNOWN),
                                     ('mid', 3, Status.SOLVABLE), ('impossible', 999, Status.UNSOLVABLE)):
            t = task(name, reward)
            recorder.prediction(str(t.task_dir), forecast)
            candidates.append(Candidate(t, FeasibilityResult(status, 'test'), forecast))
        calls = []
        async def adapter(candidate, ledger):
            async def request():
                calls.append(candidate.task.task_id)
                return Usage(0, 3)
            await ledger.execute(candidate.prediction.high_units, request, lambda r: r)
            return 'answer'
        results = asyncio.run(run_paid(candidates, budget, adapter, recorder, max_calls=10))
        self.assertEqual(calls, ['high', 'mid', 'low'])
        self.assertEqual(len(results), 3)
        self.assertEqual(budget.actual, 90)
        self.assertLessEqual(budget.actual, budget.limit)
        # Fresh zero-budget run: no fake model calls, original predictions kept;
        # skipped candidates never become training observations with cost=0.
        calls.clear()
        asyncio.run(run_paid(candidates, BudgetManager(0), adapter, recorder, max_calls=10))
        self.assertEqual(calls, [])
        self.assertIn('"skip_reason": "budget"', stream.getvalue())
        self.assertNotIn('training', stream.getvalue())

    def test_B04_B12_cli_zero_budget_predictions_before_solving(self):
        from docs.codex.tools.prepare_samples import prepare
        import run_agent
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            fixtures = Path(directory) / 'fresh'
            prepare(root / 'docs/codex/materials/original/task-dir.zip', fixtures)
            metrics = Path(directory) / 'events.jsonl'
            with patch.dict('os.environ', {'BUDGET': '0'}), \
                 patch('sys.argv', ['run_agent.py', '--tasks-dir', str(fixtures / 'tasks'),
                                    '--metrics-path', str(metrics)]), \
                 patch('socket.socket', side_effect=AssertionError('network')), \
                 patch('src.verification.subprocess.Popen', side_effect=AssertionError('task code')):
                self.assertEqual(run_agent.main(), 0)
            records = [json.loads(line) for line in metrics.read_text().splitlines()]
            self.assertEqual([r['event'] for r in records[:8]], ['task_prediction'] * 8)
            self.assertEqual(len(list((fixtures / 'tasks').glob('*/answer.txt'))), 6)
            self.assertEqual(records[-1]['actual_units'], 0)
            self.assertEqual(records[-1]['unresolved_units'], 0)


if __name__ == '__main__':
    unittest.main()
