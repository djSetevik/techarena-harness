"""Counterexamples discovered by the stage-5 review; no task code execution."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from src.answer_writer import save_answer
from src.budget import BudgetManager, Usage
from src.coding import snapshot
from src.domain import TaskSpec, Status, FeasibilityResult
from src.estimator import predict
from src.feasibility import data, search
from src.math_solver import analyze
from src.oj_adapter import OJAdapter
from src.scheduler import Candidate, run_paid
from src.task_loader import read_bytes
from src.telemetry import Recorder


QUERY = "The file orders.csv. How many units of product 'widget' were sold in months 5 through 6 inclusive?"


class Review(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_R01_query_modifiers_cannot_create_false_insufficiency(self):
        (self.root / 'orders.csv').write_text('product,month,units\nwidget,5,\n')
        for suffix in ('Treat empty units as 0.', 'Only count region East.', 'Use quantity instead of units.'):
            result = data(QUERY + ' ' + suffix, self.root)
            self.assertEqual(result.status, Status.UNKNOWN)
            self.assertIsNone(result.answer)
        (self.root / 'kb').mkdir()
        (self.root / 'kb/facts.md').write_text('# Ada\nEmployer: Firm\n')
        self.assertEqual(search('Closed KB schema v1. In which year was Ada born? '
                                'The answer can be derived from the founding year.', self.root).status, Status.UNKNOWN)

    def test_R02_exact_product_and_missing_filter(self):
        (self.root / 'orders.csv').write_text('product,month,units\nWidget,5,\nwidget,5,4\n')
        self.assertEqual(data(QUERY, self.root).answer, '4')
        (self.root / 'orders.csv').write_text('product,month,units\n,5,7\n')
        self.assertEqual(data(QUERY, self.root).status, Status.UNKNOWN)

    def test_distinct_case_entity_names_do_not_merge(self):
        (self.root / 'kb').mkdir()
        (self.root / 'kb/facts.md').write_text('# Ada\nBorn: 1980\n# ADA\nBorn: 1990\n')
        for name, expected in (('Ada', '1980'), ('ADA', '1990')):
            self.assertEqual(search(f'Closed KB schema v1. In which year was {name} born?', self.root).answer, expected)
        self.assertEqual(search('Closed KB schema v1. In which year was ada born?', self.root).status, Status.UNKNOWN)

    def test_R03_invalid_normalizer_never_refunds_sent_request(self):
        budget = BudgetManager(100)
        async def request():
            return object()
        with self.assertRaises(ValueError):
            asyncio.run(budget.execute(60, request, lambda response: {}))
        self.assertEqual(budget.unresolved, 60)
        self.assertEqual(budget.snapshot()['reserved_units'], 0)
        self.assertTrue(budget.closed)

    def test_R04_telemetry_failure_preserves_actual_usage(self):
        budget = BudgetManager(10000)
        recorder = Recorder(io.StringIO())
        task = TaskSpec('unused', 'math', 'question', 1, 'exact_int', self.root, self.root)
        recorder.prediction('scope', predict(task))
        emit = recorder.emit
        def fail_usage(event, *args, **kwargs):
            if event == 'llm_usage':
                raise OSError('synthetic full stream')
            return emit(event, *args, **kwargs)
        handle = SimpleNamespace(invoke=AsyncMock(return_value=SimpleNamespace(content='answer',
            usage_metadata=dict(input_tokens=10, output_tokens=5))))
        adapter = OJAdapter(budget, recorder, model_name='fixed', model=handle)
        with patch.object(recorder, 'emit', side_effect=fail_usage):
            with self.assertRaises(OSError):
                asyncio.run(adapter.invoke('scope', [], output_cap=1))
        self.assertEqual(budget.actual, 60)
        self.assertEqual(budget.unresolved, 0)
        self.assertEqual(budget.snapshot()['reserved_units'], 0)

    def test_concurrent_unknown_usage_events_are_task_scoped(self):
        budget = BudgetManager(100000)
        recorder = Recorder(io.StringIO())
        for name in ('one', 'two'):
            task = TaskSpec(name, 'math', 'question', 1, 'exact_int', self.root, self.root)
            recorder.prediction(name, predict(task))
        async def invoke(**kwargs):
            await asyncio.sleep(0)  # ensure both requests are already sent
            return SimpleNamespace(content='answer', usage_metadata=None)
        adapter = OJAdapter(budget, recorder, model_name='fixed', model=SimpleNamespace(invoke=invoke))
        async def requests():
            await asyncio.gather(*(adapter.invoke(name, [], output_cap=1) for name in ('one', 'two')))
        asyncio.run(requests())
        unresolved = [json.loads(line) for line in recorder.stream.getvalue().splitlines()
                      if json.loads(line)['event'] == 'unresolved_usage']
        self.assertEqual({e['scope'] for e in unresolved}, {'one', 'two'})
        self.assertEqual(sum(e['units'] for e in unresolved), budget.unresolved)

    def test_R05_competing_writers_never_overwrite(self):
        (self.root / 'task.json').write_text('{}')
        barrier = threading.Barrier(2)
        factory = tempfile.NamedTemporaryFile
        def synchronized(*args, **kwargs):
            stream = factory(*args, **kwargs)
            barrier.wait(timeout=3)
            return stream
        def write(answer):
            try:
                save_answer(self.root, answer)
                return 'saved'
            except FileExistsError:
                return 'preserved'
        with patch('src.answer_writer.tempfile.NamedTemporaryFile', side_effect=synchronized), \
             ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(write, ('first', 'second')))
        self.assertCountEqual(outcomes, ['saved', 'preserved'])
        self.assertIn((self.root / 'answer.txt').read_text(), ('first\n', 'second\n'))
        self.assertEqual(list(self.root.glob('.answer-*')), [])

    def test_R06_regular_single_bounded_read(self):
        fifo = self.root / 'pipe'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            read_bytes(fifo, self.root)
        fifo.unlink()
        source = self.root / 'source.py'
        source.write_bytes(b'123456789')
        with self.assertRaises(ValueError):
            read_bytes(source, self.root, limit=8)
        # Snapshot must use bytes from the bounded read, not reread with Path.
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded reread')):
            self.assertEqual(snapshot(self.root), {'source.py': b'123456789'})

    def test_R07_candidate_without_request_does_not_consume_call_cap(self):
        budget = BudgetManager(100000)
        recorder = Recorder(io.StringIO())
        candidates = []
        for name, reward in (('unsupported', 9), ('eligible', 1)):
            task = TaskSpec(name, 'math', 'question', reward, 'exact_int', self.root / name, self.root / name)
            prediction = predict(task)
            recorder.prediction(str(task.task_dir), prediction)
            candidates.append(Candidate(task, FeasibilityResult(Status.UNKNOWN, 'test'), prediction))
        class Adapter:
            calls = 0
            async def __call__(self, candidate, ledger):
                if candidate.task.task_id == 'unsupported':
                    return None
                async def request():
                    self.calls += 1
                    return Usage(1, 1)
                await ledger.execute(20, request, lambda response: response)
                return 'answer'
        adapter = Adapter()
        results = asyncio.run(run_paid(candidates, budget, adapter, recorder, max_calls=1))
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(results[-1][1], 'answer')

    def test_R08_existing_answer_skips_model_and_preserves_content(self):
        import run_agent
        tasks = self.root / 'tasks'
        directory = tasks / 'task'
        directory.mkdir(parents=True)
        (directory / 'task.json').write_text(json.dumps(dict(task_type='math', instruction='Unknown query', reward=5)))
        (directory / 'answer.txt').write_text('existing-user-answer\n')
        budget = BudgetManager(100000)
        recorder = Recorder(io.StringIO())
        handle = SimpleNamespace(invoke=AsyncMock(side_effect=AssertionError('paid call')))
        adapter = OJAdapter(budget, recorder, model_name='fixed', model=handle)
        run_agent.run(SimpleNamespace(tasks_dir=tasks, max_llm_calls=3), budget, recorder, adapter=adapter)
        self.assertEqual((directory / 'answer.txt').read_text(), 'existing-user-answer\n')
        self.assertEqual(handle.invoke.await_count, 0)
        self.assertEqual(budget.actual, 0)
        self.assertIn('"skip_reason": "existing_answer"', recorder.stream.getvalue())

    def test_R09_F13_F14_F15_exact_integer_dependency(self):
        for expression, expected in (('x*0', '0'), ('(x-x)+7', '7'), ('x*x-x*x', '0')):
            result = analyze(f'Let x be an arbitrary integer. Evaluate {expression}.')
            self.assertEqual(result.status, Status.SOLVABLE)
            self.assertEqual(result.answer, expected)
        for expression in ('x*2', 'x*(x-1)', 'x*x+3'):
            result = analyze(f'Let x be an arbitrary integer. Evaluate {expression}.')
            self.assertEqual(result.status, Status.UNSOLVABLE)
            self.assertEqual(len(set(result.evidence[0].possible_answers)), 2)
        for expression in ('x/2', 'x**20', '__import__("os")', 'x+y'):
            self.assertEqual(analyze(f'Let x be an arbitrary integer. Evaluate {expression}.').status, Status.UNKNOWN)

    def test_F16_F17_F18_F19_coding_never_infers_impossibility_from_io(self):
        from src.feasibility import detect
        for instruction in ('Implement a function returning its argument.',
                            'Tests fail; repair the function.',
                            'No source file; tests fully specify a square function.',
                            'Produce an unspecified result.'):
            task = TaskSpec('unused', 'coding', instruction, 1, 'unittest', self.root, self.root)
            self.assertEqual(detect(task).status, Status.UNKNOWN)

    def test_R10_F20_missing_credentials_preserve_deterministic_pass(self):
        import run_agent
        tasks = self.root / 'tasks'
        for name, kind, instruction in (
                ('constant', 'math', 'Let x be an arbitrary integer. Evaluate x*0.'),
                ('free', 'math', 'Let x be an arbitrary integer. Evaluate x*2.'),
                ('unknown', 'coding', 'Repair unspecified implementation.')):
            directory = tasks / name
            directory.mkdir(parents=True)
            (directory / 'task.json').write_text(json.dumps(dict(task_type=kind, instruction=instruction, reward=1)))
        metrics = self.root / 'events.jsonl'
        with patch.dict('os.environ', {'BUDGET': '100000', 'LLM_BASE_URL': '', 'LLM_API_KEY': ''}), \
             patch('sys.argv', ['run_agent.py', '--tasks-dir', str(tasks), '--enable-llm',
                 '--model', 'qwen3.8-27b', '--reasoning-usage', 'included', '--metrics-path', str(metrics)]), \
             patch('socket.socket', side_effect=AssertionError('network')):
            self.assertEqual(run_agent.main(), 0)
        self.assertEqual((tasks / 'constant/answer.txt').read_text(), '0\n')
        self.assertFalse((tasks / 'free/answer.txt').exists())
        records = [json.loads(line) for line in metrics.read_text().splitlines()]
        self.assertTrue(any(e.get('skip_reason') == 'credentials' and e['scope'].endswith('/unknown') for e in records))
        self.assertTrue(any(e['event'] == 'feasibility' and e['status'] == 'UNSOLVABLE' and e['scope'].endswith('/free') for e in records))
        self.assertEqual(records[-1]['actual_units'], 0)


if __name__ == '__main__':
    unittest.main()
