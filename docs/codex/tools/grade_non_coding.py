#!/usr/bin/env python3
"""Development-only grading of supplied non-coding sample answers.

Never run this inside the competition solver. It reads separated expected labels
and does not execute task programs, pytest, or an LLM. Coding results are NOT graded.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks-dir', required=True, type=Path)
    parser.add_argument('--labels', required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.tasks_dir.resolve(strict=True)
        labels = json.loads(args.labels.read_text(encoding='utf-8'))
        if not isinstance(labels, dict):
            raise ValueError('Labels must be an object')
        checked = passed = skipped_coding = 0
        reward = 0.0
        for directory, meta in sorted(labels.items()):
            if Path(directory).name != directory or directory in {'.', '..'} or '/' in directory or '\\' in directory:
                raise ValueError('Invalid task directory in labels')
            if meta['task_type'] == 'coding':
                skipped_coding += 1
                print(f'{directory}: NOT GRADED (coding requires separate isolated tests)')
                continue
            checked += 1
            answer = root / directory / 'answer.txt'
            if not answer.is_file():
                print(f'{directory}: MISSING')
                continue
            if not answer.resolve().is_relative_to(root) or answer.stat().st_size > 4096:
                raise ValueError('Unsafe or oversized answer file')
            actual = answer.read_text(encoding='utf-8-sig').strip()
            expected = str(meta['expected']).strip()
            kind = meta['check']
            if kind == 'exact_int':
                valid = re.fullmatch(r'[+-]?\d+', actual) is not None
                ok = valid and int(actual) == int(expected)
            elif kind == 'exact_str':
                ok = actual == expected
            else:
                raise ValueError(f'Unsupported non-coding checker: {kind}')
            print(f"{directory}: {'PASS' if ok else 'FAIL'}")
            if ok:
                passed += 1
                reward += float(meta['reward'])
        print(f'Non-coding sample matches: {passed}/{checked}; verified sample reward: {reward:g}')
        print(f'Coding not graded: {skipped_coding}. This is not the official hidden evaluator.')
        return 0 if checked and passed == checked else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
