"""Build-only parallel wheel retrieval, followed by offline constrained install.

No dependency resolution is parallelized: every download is --no-deps and each
name/version comes from the explicit lock. The final offline install resolves
the requirements against this complete local wheel set and runs pip check.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def locked_lines(path):
    lines = [line.strip() for line in path.read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if not lines or any(re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+', line) is None for line in lines):
        raise ValueError('Every build dependency must have one exact version')
    return lines


def install(constraints, requirements, workers=4):
    lines = locked_lines(constraints)
    with tempfile.TemporaryDirectory(prefix='techarena-build-') as directory:
        root = Path(directory)
        wheels = root / 'wheels'
        wheels.mkdir()
        groups = []
        for index in range(workers):
            group = root / f'group-{index}.txt'
            group.write_text('\n'.join(lines[index::workers]) + '\n')
            groups.append(group)
        def download(group):
            subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps',
                '--only-binary=:all:', '--progress-bar', 'off', '--disable-pip-version-check',
                '--dest', str(wheels), '--requirement', str(group)], check=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(download, groups))
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '--no-index',
            '--find-links', str(wheels), '--constraint', str(constraints),
            '--requirement', str(requirements)], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)


if __name__ == '__main__':
    install(Path(sys.argv[1]), Path(sys.argv[2]))
