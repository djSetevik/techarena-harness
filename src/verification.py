"""Bounded subprocess runner for an explicitly isolated, non-root deployment.

Not a sandbox. Container mounts/network/UID policy must provide isolation.
Never enables itself merely because a timeout or AST check is available.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile


@dataclass(frozen=True)
class Verification:
    passed: bool
    reason: str
    diagnostic: str = ''


class IsolatedRunner:
    def __init__(self, *, isolated=False, timeout=15, output_bytes=65536):
        if not isolated or os.geteuid() == 0:
            raise ValueError('Coding execution requires explicitly isolated non-root deployment')
        if not 0 < timeout <= 60 or not 0 < output_bytes <= 1024 * 1024:
            raise ValueError('Invalid verification limits')
        self.timeout, self.output_bytes = timeout, output_bytes

    def __call__(self, workspace: Path, test_entry: str) -> Verification:
        if os.geteuid() == 0:
            raise ValueError('Refusing task execution as root')
        from src.task_loader import scoped
        entry = scoped(workspace / test_entry, workspace)
        def limits():
            resource.setrlimit(resource.RLIMIT_CPU, (self.timeout, self.timeout + 1))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
            resource.setrlimit(resource.RLIMIT_FSIZE, (self.output_bytes, self.output_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with tempfile.TemporaryDirectory(dir=workspace) as home, tempfile.TemporaryFile() as output:
            environment = {'PATH': os.defpath, 'HOME': home, 'PYTHONDONTWRITEBYTECODE': '1',
                           'PYTHONNOUSERSITE': '1', 'LANG': 'C.UTF-8'}
            process = subprocess.Popen([sys.executable, '-B', '-s', str(entry)], cwd=workspace,
                env=environment, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=limits)
            reason = 'tests_failed'
            try:
                process.wait(timeout=self.timeout)
                reason = 'passed' if process.returncode == 0 else 'tests_failed'
            except subprocess.TimeoutExpired:
                reason = 'timeout'
            finally:
                # Kill descendants even when the parent completed successfully.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            output.seek(0)
            diagnostic = output.read(self.output_bytes).decode('utf-8', errors='replace')
            return Verification(reason == 'passed', reason, diagnostic[-4096:])
