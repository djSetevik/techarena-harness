"""TechArena 2026 starter harness, not a finished competition solution.

Each task has task.json and optionally workspace/. Answers are saved immediately
both in task directory and workspace if present, to accommodate the sample's
'current directory' instruction and the written competition rubric.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from src.solvers import solve_task

LOG = logging.getLogger('techarena')


def save_answer(task_dir: Path, workspace: Path, answer: str) -> None:
    """Save task output atomically, without assuming OUT is set."""
    for parent in (task_dir, workspace) if workspace != task_dir else (task_dir,):
        final = parent / 'answer.txt'
        temporary = parent / 'answer.txt.tmp'
        temporary.write_text(answer.strip() + '\n', encoding='utf-8')
        temporary.replace(final)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks-dir', required=True, type=Path)
    parser.add_argument('--max-llm-calls', type=int, default=int(os.getenv('MAX_LLM_CALLS','3')))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    if not args.tasks_dir.is_dir():
        parser.error(f'Tasks directory not found: {args.tasks_dir}')
    tasks = []
    for path in args.tasks_dir.glob('*/task.json'):
        try:
            task = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(task, dict) and 'instruction' in task:
                tasks.append((path.parent, task))
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning('Cannot read %s: %s', path, exc)

    # Placeholder budget-aware ordering: deterministic tasks first and then
    # harder ones by reward.  A trained cost/success estimator comes later.
    cost_rank = {'math': 0, 'data_analysis': 1, 'search': 2, 'coding': 3}
    tasks.sort(key=lambda item: (cost_rank.get(item[1].get('task_type'), 4),
                                 -float(item[1].get('reward', 0))))
    llm_remaining = max(0, args.max_llm_calls)
    solved = 0
    reward = 0
    start = time.monotonic()
    for task_dir, task in tasks:
        workspace = task_dir / 'workspace' if (task_dir / 'workspace').is_dir() else task_dir
        task_id = str(task.get('task_id', task_dir.name))
        is_coding = task.get('task_type') == 'coding'
        if is_coding and (not llm_remaining or not os.getenv('LLM_BASE_URL') or not os.getenv('LLM_API_KEY')):
            LOG.info('%s skipped (no LLM budget or proxy credentials)', task_id)
            continue
        try:
            result, used_llm = solve_task(task, workspace, allow_llm=bool(llm_remaining))
            llm_remaining -= int(used_llm)
            if result is None:
                LOG.info('%s unresolved', task_id)
                continue
            save_answer(task_dir, workspace, result)
            solved += 1
            reward += float(task.get('reward', 0))
            LOG.info('%s saved (reward=%s)', task_id, task.get('reward', 0))
        except Exception as exc:
            LOG.warning('%s failed: %s', task_id, exc)
    LOG.info('Completed: %s/%s tasks, claimed reward %.1f, elapsed %.1fs', solved,
             len(tasks), reward, time.monotonic() - start)
    # Claims are local heuristics, only the hidden evaluator confirms points.
    return 0


if __name__ == '__main__':
    sys.exit(main())
