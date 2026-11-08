#!/usr/bin/env python3
"""Prepare fresh development fixtures without exposing labels to the runtime.

Does not execute task code, contact a model, or overwrite an existing output.
Python 3.10+; standard library only. This is a development utility, not a solver.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

MAX_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 5000


def prepare(source: Path, output: Path) -> dict[str, object]:
    source = source.resolve(strict=True)
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output already exists: {output}. Choose a NEW directory; nothing was overwritten.")
    files: dict[PurePosixPath, bytes] = {}
    labels: dict[str, object] = {}
    total = 0
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("Archive has too many entries")
        for member in members:
            raw = member.filename
            # Validate even paths that will not be copied.
            p = PurePosixPath(raw)
            if "\\" in raw or p.is_absolute() or ".." in p.parts:
                raise ValueError(f"Unsafe archive path: {raw!r}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Symlinks are not accepted: {raw!r}")
            if member.is_dir() or not p.parts:
                continue
            # AppleDouble resource forks are not UTF-8 task files.
            if any(part.startswith('.') or part == '__MACOSX' for part in p.parts):
                continue
            if p.parts[0] != 'task-dir' or len(p.parts) < 3:
                continue
            if p.name in {'answer.txt', 'answer.txt.tmp'} or '__pycache__' in p.parts or p.suffix in {'.pyc', '.pyo'}:
                continue
            if member.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"File too large: {raw!r}")
            total += member.file_size
            if total > MAX_BYTES:
                raise ValueError("Archive exceeds extraction limit")
            rel = PurePosixPath(*p.parts[1:])
            if rel in files:
                raise ValueError(f"Duplicate archive entry: {raw!r}")
            blob = archive.read(member)
            if len(p.parts) == 3 and p.name == 'task.json':
                task = json.loads(blob.decode('utf-8-sig'))
                if not isinstance(task, dict):
                    raise ValueError(f"Task must be a JSON object: {raw!r}")
                directory = p.parts[1]
                required = ('task_id', 'task_type', 'instruction', 'reward', 'check')
                missing = [k for k in required if k not in task]
                if missing:
                    raise ValueError(f"Missing metadata in {raw!r}: {missing}")
                expected = task.pop('expected', None)
                labels[directory] = {
                    'task_type': task['task_type'],
                    'check': task['check'],
                    'reward': task['reward'],
                    'expected': expected,
                }
                blob = (json.dumps(task, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            files[rel] = blob
    if not labels:
        raise ValueError("No task-dir/<task>/task.json entries found")
    # All archive validation is complete before any output is written.
    output.mkdir(parents=True, exist_ok=False)
    tasks_root = output / 'tasks'
    eval_root = output / 'evaluation'
    tasks_root.mkdir()
    eval_root.mkdir()
    for rel, blob in files.items():
        destination = tasks_root.joinpath(*rel.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(blob)
    label_file = eval_root / 'official_answers.json'
    label_file.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {
        'purpose': 'development-only; never mount evaluation/ into the solver container',
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'task_count': len(labels),
        'runtime_files': len(files),
        'labels_separate': True,
        'runtime_files_sha256': {str(p): hashlib.sha256(b).hexdigest() for p, b in sorted(files.items(), key=lambda x: str(x[0]))},
    }
    (output / 'fixture_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'tasks': str(tasks_root), 'labels': str(label_file), 'count': len(labels)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().parents[1] / 'materials' / 'original' / 'task-dir.zip'
    parser.add_argument('--input', type=Path, default=default)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.input, args.out)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print(f"Prepared {result['count']} task directories without expected.")
    print(f"Runtime input: {result['tasks']}")
    print(f"Evaluation only (do not give to solver): {result['labels']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
