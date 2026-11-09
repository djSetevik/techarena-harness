"""Signal test of trusted harness code, never a task-program subprocess."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest


class Interrupt(unittest.TestCase):
    def test_D05_native_sigterm_preserves_saved_answers(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tasks = root / 'tasks'
            for name, reward in (('first', 5), ('second', 1)):
                task = tasks / name
                task.mkdir(parents=True)
                (task / 'task.json').write_text(json.dumps(dict(task_type='math', reward=reward,
                    instruction='A warehouse starts with 20 boxes. It ships 2 boxes per day for 3 days. How many boxes does it have at the end?',
                    check='exact_int')))
            metrics = root / 'events.jsonl'
            script = '''
import run_agent
import sys
import time
original = run_agent.detect
calls = 0
def pause_on_second(*args, **kwargs):
    global calls
    calls += 1
    if calls == 2:
        print('READY', flush=True)
        time.sleep(30)
    return original(*args, **kwargs)
run_agent.detect = pause_on_second
sys.argv = ['run_agent.py', '--tasks-dir', sys.argv[1], '--metrics-path', sys.argv[2], '--max-llm-calls', '0']
raise SystemExit(run_agent.main())
'''
            process = subprocess.Popen([sys.executable, '-c', script, str(tasks), str(metrics)],
                cwd=repo, env={'PATH': os.defpath, 'BUDGET': '0', 'PYTHONDONTWRITEBYTECODE': '1'},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=5), 'Harness did not reach second task')
                self.assertEqual(process.stdout.readline().strip(), 'READY')
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143, stderr)
                self.assertEqual((tasks / 'first/answer.txt').read_text(), '14\n')
                self.assertFalse((tasks / 'second/answer.txt').exists())
                self.assertEqual(list(tasks.rglob('.answer-*')), [])
                records = [json.loads(line) for line in metrics.read_text().splitlines()]
                self.assertEqual(records[-1]['event'], 'run_interrupted')
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == '__main__':
    unittest.main()
