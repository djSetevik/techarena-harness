"""Reproduce the archived starter, without task execution or network access."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from docs.codex.tools.prepare_samples import prepare


ROOT = Path(__file__).resolve().parents[1]


class ArchivedBaseline(unittest.TestCase):
    def test_A02_archived_starter(self):
        archive = ROOT / 'docs/codex/materials/baseline/techarena-harness-starter.zip'
        source = ROOT / 'docs/codex/materials/original/task-dir.zip'
        archives = {p: hashlib.sha256(p.read_bytes()).digest() for p in (archive, source)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / 'baseline'
            baseline.mkdir()
            # Extract only the three trusted development files needed for this run.
            with zipfile.ZipFile(archive) as zipped:
                for name in ('run_agent.py', 'src/solvers.py', 'src/__init__.py'):
                    target = baseline / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zipped.read(name))
            fixtures = root / 'fixtures'
            prepare(source, fixtures)
            tasks = fixtures / 'tasks'
            inputs = {p: p.read_bytes() for p in tasks.rglob('*') if p.is_file()}
            # The starter skips coding before entering solve_task when the call
            # cap is zero. Guards make accidental task execution/network a failure.
            runner = '''
import runpy
import sys
from unittest.mock import patch
sys.argv = ['run_agent.py', '--tasks-dir', sys.argv[1], '--max-llm-calls', '0']
with patch('socket.socket', side_effect=AssertionError('network forbidden')), \\
     patch('subprocess.run', side_effect=AssertionError('task execution forbidden')):
    runpy.run_path('run_agent.py', run_name='__main__')
'''
            result = subprocess.run(
                [sys.executable, '-c', runner, str(tasks)], cwd=baseline,
                env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'},
                capture_output=True, text=True, timeout=30, check=True)
            self.assertIn('Completed: 6/8 tasks', result.stderr)
            self.assertEqual(len(list(tasks.glob('*/answer.txt'))), 6)
            # The baseline's duplicate-output bug is reproduced, not accepted
            # as the contract for the updated runtime.
            self.assertEqual(len(list(tasks.glob('*/workspace/answer.txt'))), 4)
            self.assertTrue(all(p.read_bytes() == blob for p, blob in inputs.items()))
            graded = subprocess.run(
                [sys.executable, str(ROOT / 'docs/codex/tools/grade_non_coding.py'),
                 '--tasks-dir', str(tasks), '--labels',
                 str(fixtures / 'evaluation/official_answers.json')],
                env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'},
                capture_output=True, text=True, timeout=30, check=True)
            self.assertIn('Non-coding sample matches: 6/6', graded.stdout)
            self.assertIn('verified sample reward: 16', graded.stdout)
        self.assertTrue(all(hashlib.sha256(p.read_bytes()).digest() == digest
                            for p, digest in archives.items()))


if __name__ == '__main__':
    unittest.main()
