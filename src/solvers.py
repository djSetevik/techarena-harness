"""Cheap deterministic solvers. All model work belongs to oj_adapter."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def solve_math(instruction: str) -> str | None:
    # Consume every operation; finding a few familiar fragments is insufficient.
    parts = re.fullmatch(
        r'A warehouse starts with (\d+) boxes\.\s*(.*?)'
        r'How many boxes does it have at the end\?(.*)', instruction, re.I | re.S)
    if not parts:
        return None
    # Only operational boilerplate is ignored after the target question.
    suffix = parts[3].strip()
    boilerplate = (
        'Compute it with the bash tool (python3 -c). '
        'Work only inside the current directory. '
        'When you are done, write ONLY the final answer to the file answer.txt in the current directory '
        '(for example with bash: echo 42 > answer.txt).')
    if suffix and suffix != boilerplate:
        return None
    value = int(parts[1])
    for sentence in filter(None, (s.strip() for s in parts[2].split('.'))):
        split = re.fullmatch(r'Then the stock is split equally into (\d+) warehouses and it keeps one share \(rounded down\)', sentence, re.I)
        doubled = re.fullmatch(r'Then the stock is doubled by merging with a sister warehouse', sentence, re.I)
        shipped = re.fullmatch(r'It ships (\d+) boxes per day for (\d+) days', sentence, re.I)
        received = re.fullmatch(r'It receives (\d+) deliveries of (\d+) boxes each', sentence, re.I)
        if split and int(split[1]) > 0:
            value //= int(split[1])
        elif doubled:
            value *= 2
        elif shipped:
            value -= int(shipped[1]) * int(shipped[2])
        elif received:
            value += int(received[1]) * int(received[2])
        else:
            return None
    return str(value)


def solve_data(instruction: str, workspace: Path) -> str | None:
    from src.feasibility import data
    return data(instruction, workspace).answer


def solve_search(instruction: str, workspace: Path) -> str | None:
    from src.feasibility import search
    return search(instruction, workspace).answer


def solve_task(task: dict[str, Any], workspace: Path, allow_llm: bool = False) -> tuple[str | None, bool]:
    # Compatibility signature only. It can never trigger an unbudgeted call.
    kind, instruction = task.get('task_type'), str(task.get('instruction', ''))
    if kind == 'math':
        from src.math_solver import analyze
        return analyze(instruction).answer, False
    if kind == 'data_analysis':
        return solve_data(instruction, workspace), False
    if kind == 'search':
        return solve_search(instruction, workspace), False
    return None, False
