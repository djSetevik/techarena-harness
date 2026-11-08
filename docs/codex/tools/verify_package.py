#!/usr/bin/env python3
"""Check the kit's manifest locally; no network, credentials, or task execution."""
from pathlib import Path
import hashlib
import json
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        manifest = json.loads((root / 'package_manifest.json').read_text(encoding='utf-8'))
        problems = []
        for item in manifest['files']:
            relative = item['path']
            path = root / relative
            if not path.resolve().is_relative_to(root):
                raise ValueError('Manifest contains a path outside the kit')
            if not path.is_file():
                problems.append(f'MISSING: {relative}')
                continue
            blob = path.read_bytes()
            if len(blob) != item['size_bytes'] or hashlib.sha256(blob).hexdigest() != item['sha256']:
                problems.append(f'CHANGED: {relative}')
        if problems:
            print('\n'.join(problems))
            return 1
        print(f"OK: {len(manifest['files'])} files match package_manifest.json")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
