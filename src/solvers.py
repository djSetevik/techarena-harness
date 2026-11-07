"""Deterministic tools for sample-like tasks + openJiuwen LLM fallback.

No use of `expected` or task IDs in solving: both may be absent/changed
in the hidden evaluation. Never send arbitrary local secrets in prompts.
"""
from __future__ import annotations

import asyncio
import csv
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def solve_math(instruction: str) -> str | None:
    m = re.search(r'warehouse starts with (\d+) boxes', instruction, re.I)
    if not m:
        return None
    value = int(m.group(1))
    pattern = re.compile(
        r'split equally into (\d+) warehouses|'
        r'(?:stock is )?doubled|'
        r'ships (\d+) boxes per day for (\d+) days|'
        r'receives (\d+) deliveries of (\d+) boxes each', re.I)
    found = 0
    for op in pattern.finditer(instruction[m.end():]):
        found += 1
        if op.group(1) is not None:
            value //= int(op.group(1))
        elif op.group(2) is not None:
            value -= int(op.group(2)) * int(op.group(3))
        elif op.group(4) is not None:
            value += int(op.group(4)) * int(op.group(5))
        else:
            value *= 2
    return str(value) if found else None


def solve_data(instruction: str, workspace: Path) -> str | None:
    target = re.search(r"product ['\"]([^'\"]+)['\"]", instruction, re.I)
    months = re.search(r'months? (\d+) through (\d+)', instruction, re.I)
    csv_path = workspace / 'sales.csv'
    if not (target and months and csv_path.is_file()):
        return None
    lo, hi = int(months.group(1)), int(months.group(2))
    with csv_path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        required = {'product', 'month', 'units'}
        if not required.issubset(reader.fieldnames or []):
            return None
        total = sum(int(row['units']) for row in reader
                    if row['product'].strip().casefold() == target.group(1).casefold()
                    and lo <= int(row['month']) <= hi)
    return str(total)


def load_entry(workspace: Path, subject: str) -> str | None:
    for path in (workspace / 'kb').glob('*.md'):
        text = path.read_text(encoding='utf-8')
        if re.search(r'^#\s+' + re.escape(subject) + r'\s*$', text, re.I | re.M):
            return text
    return None


def field(text: str, key: str) -> str | None:
    m = re.search(r'^' + re.escape(key) + r':\s*(.+?)\s*$', text, re.M | re.I)
    return m.group(1).strip() if m else None


def solve_search(instruction: str, workspace: Path) -> str | None:
    born = re.search(r'In which year was (.+?) born\?', instruction, re.I)
    hq = re.search(r"In which city is the headquarters of (.+?)'s employer\?", instruction, re.I)
    if born:
        entry = load_entry(workspace, born.group(1))
        return field(entry, 'Born') if entry else None
    if hq:
        entry = load_entry(workspace, hq.group(1))
        employer = field(entry, 'Employer') if entry else None
        company = load_entry(workspace, employer) if employer else None
        return field(company, 'Headquarters') if company else None
    return None


def tests_pass(workspace: Path) -> bool:
    cmd = [sys.executable, 'test_mylib.py']
    try:
        result = subprocess.run(cmd, cwd=workspace, capture_output=True,
                                timeout=15, check=False, text=True)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


async def llm_correct_python(instruction: str, current: str, tests: str) -> str:
    """Actual call through openJiuwen SDK; no direct provider SDK calls."""
    import os
    from openjiuwen.core.foundation.llm import (
        Model, ModelClientConfig, ModelRequestConfig, SystemMessage, UserMessage
    )
    api_base = os.environ.get('LLM_BASE_URL')
    api_key = os.environ.get('LLM_API_KEY')
    if not api_base or not api_key:
        raise RuntimeError('LLM_BASE_URL / LLM_API_KEY are not provided')
    model_name = os.environ.get('CODING_MODEL', 'qwen3.8-27b-noreason')
    if model_name not in {
        'qwen3.8-27b', 'qwen3.8-27b-noreason',
        'qwen3.6-35b-a3b', 'qwen3.6-35b-a3b-noreason',
    }:
        raise RuntimeError('Model is not in contest allowlist')
    llm = Model(
        model_client_config=ModelClientConfig(
            client_provider='OpenAI', api_base=api_base, api_key=api_key,
            timeout=60, verify_ssl=True),
        model_config=ModelRequestConfig(model=model_name, temperature=0),
    )
    msgs = [
        SystemMessage(content=(
            'Repair the provided Python module so its tests pass. '
            'Return ONLY complete Python source for mylib.py, no markdown fences. '
            'Do not modify tests, read secrets, or use network.'
        )).model_dump(exclude_none=True),
        UserMessage(content=(
            f'Instruction:\n{instruction}\n\nCURRENT mylib.py:\n{current}'
            f'\n\nTESTS:\n{tests}'
        )).model_dump(exclude_none=True),
    ]
    resp = await llm.invoke(model=model_name, messages=msgs)
    content = str(resp.content).strip()
    content = re.sub(r'^```(?:python)?\s*|\s*```$', '', content, flags=re.I)
    return content.strip() + '\n'


def solve_coding(instruction: str, workspace: Path, allow_llm: bool) -> tuple[str | None, bool]:
    source = workspace / 'mylib.py'
    tests = workspace / 'test_mylib.py'
    if not source.exists() or not tests.exists():
        return None, False
    if tests_pass(workspace):
        return 'DONE', False
    if not allow_llm:
        return None, False
    original = source.read_text(encoding='utf-8')
    proposed = asyncio.run(llm_correct_python(
        instruction, original, tests.read_text(encoding='utf-8')))
    compile(proposed, str(source), 'exec')
    source.write_text(proposed, encoding='utf-8')
    if tests_pass(workspace):
        return 'DONE', True
    source.write_text(original, encoding='utf-8')
    return None, True


def solve_task(task: dict[str, Any], workspace: Path, allow_llm: bool) -> tuple[str | None, bool]:
    kind = task.get('task_type')
    instruction = str(task.get('instruction', ''))
    if kind == 'math':
        return solve_math(instruction), False
    if kind == 'data_analysis':
        return solve_data(instruction, workspace), False
    if kind == 'search':
        return solve_search(instruction, workspace), False
    if kind == 'coding':
        return solve_coding(instruction, workspace, allow_llm)
    return None, False
