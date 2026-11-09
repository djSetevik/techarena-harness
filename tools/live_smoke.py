"""Explicit small live SDK smoke; run only after owner approval of model/usage.

Not discovered by offline unittest. No task program is executed.
"""
import argparse
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.budget import BudgetManager, limit_units
from src.domain import TaskSpec
from src.estimator import predict
from src.oj_adapter import OJAdapter
from src.telemetry import Recorder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-live', action='store_true', required=True)
    parser.add_argument('--model', required=True, choices=['qwen3.8-27b', 'qwen3.6-35b-a3b'])
    parser.add_argument('--reasoning-usage', required=True, choices=['included', 'separate'])
    args = parser.parse_args()
    budget = BudgetManager(limit_units(os.getenv('BUDGET')))
    if budget.limit > 10000:
        parser.error('Smoke BUDGET must be <=1000 output tokens')
    recorder = Recorder()
    task = TaskSpec('live-smoke', 'math', 'Return only the integer 2.', 0, 'exact_int',
                    Path('/tmp/live-smoke'), Path('/tmp/live-smoke'))
    scope = str(task.task_dir)
    recorder.prediction(scope, predict(task))
    adapter = OJAdapter(budget, recorder, model_name=args.model,
        api_base=os.getenv('LLM_BASE_URL'), api_key=os.getenv('LLM_API_KEY'),
        reasoning_in_output=args.reasoning_usage == 'included', max_calls=1)
    text = asyncio.run(adapter.invoke(scope, [dict(role='user', content=task.instruction)], output_cap=16))
    recorder.emit('smoke_result', scope, exact_match=text == '2', **budget.snapshot())
    return 0 if text == '2' and budget.actual > 0 and not budget.unresolved else 1


if __name__ == '__main__':
    raise SystemExit(main())
