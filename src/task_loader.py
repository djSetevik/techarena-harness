"""Bounded, task-scoped input. No evaluation metadata leaves this module."""
import json
import math
import os
import stat
from pathlib import Path
from src.domain import TaskSpec

MAX_BYTES = 2 * 1024 * 1024


def scoped(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError('Path escapes task scope')
    return resolved


def read_bytes(path: Path, root: Path, limit: int = MAX_BYTES) -> bytes:
    path = scoped(path, root)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Only regular input files are supported')
    # Nonblocking prevents a FIFO swap from hanging between stat and open;
    # no-follow prevents a final symlink swap after scope resolution.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Only regular input files are supported')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Input size limit exceeded')
    return data


def read_text(path: Path, root: Path, limit: int = MAX_BYTES) -> str:
    return read_bytes(path, root, limit).decode('utf-8-sig')


def load_task(path: Path, tasks_root: Path) -> TaskSpec:
    # Resolve within the requested task, not merely within the batch: otherwise
    # a task.json link can silently substitute another task's workspace/context.
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Linked task directories or metadata are unsupported')
    scoped(path, path.parent)
    path = scoped(path, tasks_root)
    task_dir = path.parent
    raw = json.loads(read_text(path, task_dir))
    if not isinstance(raw, dict):
        raise ValueError('Task must be an object')
    kind = raw.get('task_type')
    if kind not in {'math', 'search', 'data_analysis', 'coding'}:
        raise ValueError('Unsupported task_type')
    if not isinstance(raw.get('instruction'), str):
        raise ValueError('instruction must be text')
    reward = raw.get('reward', 0)
    if isinstance(reward, bool) or not isinstance(reward, (int, float)) or not math.isfinite(reward) or reward < 0:
        raise ValueError('reward must be finite and nonnegative')
    workspace = task_dir / 'workspace'
    if workspace.exists() or workspace.is_symlink():
        workspace = scoped(workspace, task_dir)
        if not workspace.is_dir():
            raise ValueError('workspace must be a directory')
    else:
        workspace = task_dir
    return TaskSpec(str(raw.get('task_id', task_dir.name)), kind,
                    raw['instruction'], float(reward), str(raw.get('check', '')),
                    task_dir, workspace)
