"""One atomic output beside task.json; existing answers are preserved."""
import os
import tempfile
from pathlib import Path


def save_answer(task_dir: Path, answer: str) -> None:
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Empty answer')
    task_dir = task_dir.resolve(strict=True)
    if not (task_dir / 'task.json').is_file():
        raise ValueError('Missing task.json')
    final = task_dir / 'answer.txt'
    if final.exists() or final.is_symlink():
        raise FileExistsError('Existing answer preserved')
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=task_dir,
                                         prefix='.answer-', delete=False) as stream:
            name = stream.name
            stream.write(answer.strip() + '\n')
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        # Link publishes a fully written file atomically and fails on EEXIST.
        # A separate exists+replace would overwrite a concurrent writer.
        os.link(name, final)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)
