"""Public runtime metadata for the competition image; no credential inspection."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys

root = Path('/app')
digest = hashlib.sha256()
for path in sorted([root / 'run_agent.py', *(root / 'src').rglob('*.py')]):
    digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes() + b'\0')
constraints = [line for line in (root / 'constraints.txt').read_text().splitlines()
               if line and not line.startswith('#')]
mismatches = []
for constraint in constraints:
    name, expected = constraint.split('==', 1)
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        actual = None
    if actual != expected:
        mismatches.append(dict(name=name, expected_version=expected, actual_version=actual))
print(json.dumps(dict(uid=os.geteuid(), python=sys.version.split()[0],
    openjiuwen=importlib.metadata.version('openjiuwen'), runtime_sha256=digest.hexdigest(),
    rootfs_read_only=bool(os.statvfs('/app').f_flag & os.ST_RDONLY),
    codex_executable_present=shutil.which('codex') is not None,
    constrained_packages=len(constraints), dependency_mismatches=mismatches), indent=2))
raise SystemExit(1 if mismatches else 0)
