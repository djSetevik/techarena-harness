#!/usr/bin/env python3
"""Apply kit v2's development-permission correction locally, with backups.

No network, git operations, model calls, service changes, or dependency installs.
Run this from the extracted v2 kit and pass the competition repository to --repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def inside(root: Path, relative: str) -> Path:
    part = Path(relative)
    if part.is_absolute() or '..' in part.parts:
        raise ValueError(f'Unsafe path: {relative}')
    path = root / part
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError(f'Path is outside the repository or is a symlink: {path}')
    return path


def replace_known(text: str, rules: list[dict[str, str]], label: str) -> str:
    for index, rule in enumerate(rules, 1):
        old, new = rule['old'], rule['new']
        # New paragraphs may contain the old paragraph as a prefix.
        if new in text:
            continue
        if old not in text:
            raise ValueError(
                f'CONFLICT: {label}, fragment {index} differs from the kit. '
                'Merge it manually; no files have been written.'
            )
        text = text.replace(old, new)
    return text


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--check', action='store_true', help='Preflight only; write nothing')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    repo = args.repo.expanduser().resolve()
    if not repo.is_dir() or not (repo / '.git').exists():
        raise ValueError('--repo must point to the competition Git repository')
    destination = inside(repo, 'docs/codex')
    if destination.resolve() == source:
        raise ValueError('Run the updater from the separate extracted v2 kit, not docs/codex')

    manifest = json.loads((source / 'package_manifest.json').read_text(encoding='utf-8'))
    spec = json.loads((source / 'permission_update.json').read_text(encoding='utf-8'))
    if spec.get('revision') != 2:
        raise ValueError('This updater requires the v2 permission correction')
    files: dict[str, bytes] = {}
    for entry in manifest['files']:
        relative = entry['path']
        data = inside(source, relative).read_bytes()
        if len(data) != entry['size_bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError(f'Source package integrity error: {relative}')
        files[relative] = data
    files['package_manifest.json'] = (source / 'package_manifest.json').read_bytes()

    # Preflight the entire change set before creating backups or writing anything.
    planned: dict[Path, bytes] = {}
    custom: list[str] = []
    special = {'permission_update.json', 'tools/apply_permission_update.py'} | set(spec['add_files'])
    for relative, canonical in files.items():
        target = inside(repo, 'docs/codex/' + relative)
        if target.exists() and not target.is_file():
            raise ValueError(f'Not a regular file: {target}')
        old = target.read_bytes() if target.exists() else None
        if old is None or relative == 'package_manifest.json':
            updated = canonical
        elif relative in spec['replacements']:
            updated = replace_known(old.decode('utf-8'), spec['replacements'][relative], relative).encode('utf-8')
        elif old == canonical:
            updated = old
        elif relative in special:
            raise ValueError(f'CONFLICT: {target} exists with different contents; no files written')
        else:
            updated = old  # Do not erase unrelated user edits to scripts or documents.
        if updated != canonical:
            custom.append('docs/codex/' + relative)
        if old != updated:
            planned[target] = updated

    root_agents = inside(repo, 'AGENTS.md')
    if root_agents.exists() and not root_agents.is_file():
        raise ValueError('Root AGENTS.md is not a regular file')
    old_agents = root_agents.read_bytes() if root_agents.exists() else None
    new_agents = files['AGENTS.md'] if old_agents is None else replace_known(
        old_agents.decode('utf-8'), spec['replacements']['AGENTS.md'], 'AGENTS.md (repository root)'
    ).encode('utf-8')
    if old_agents != new_agents:
        planned[root_agents] = new_agents

    for target in planned:
        print('UPDATE:', target.relative_to(repo))
    if args.check:
        print(f'CHECK OK: {len(planned)} files would change. Nothing written.')
        return 0
    if not planned:
        print('ALREADY UPDATED: no files changed.')
        return 0

    backup_parent = inside(repo, '.local/codex-permission-backups')
    backup_parent.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='v2-', dir=backup_parent))
    created = []
    for target in planned:
        relative = target.relative_to(repo)
        if target.exists():
            copy = backup / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, copy)
        else:
            created.append(str(relative))
    (backup / '_new_files.json').write_text(json.dumps(created, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for target, content in planned.items():
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
        atomic_write(target, content, mode)
    print(f'UPDATED: {len(planned)} files. Backup: {backup}')
    if custom:
        print('Preserved user edits (manifest may report CHANGED): ' + ', '.join(custom))
    print('Development permission is closed under U1; runtime restrictions remain unchanged.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(2)
