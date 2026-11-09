"""Private stdin/stdout worker for the bounded live evaluation controller.

Model workers never execute task code. Verification workers never receive proxy
credentials or a network interface. Both run in disposable non-root containers.
"""
import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, '/app')


def model(payload):
    from src.budget import BudgetManager
    from src.domain import TaskSpec
    from src.estimator import predict
    from src.oj_adapter import OJAdapter
    from src.telemetry import Recorder
    budget = BudgetManager(payload['reservation_units'])
    events = io.StringIO()
    recorder = Recorder(events)
    scope = '/tmp/live-request'
    task = TaskSpec('request', 'coding', 'Budgeted controller request', 0, '', Path(scope), Path(scope))
    recorder.prediction(scope, predict(task))
    text, error, error_fields = None, None, {}
    try:
        adapter = OJAdapter(budget, recorder, model_name=payload['model'],
            api_base=os.environ['LLM_BASE_URL'], api_key=os.environ['LLM_API_KEY'],
            timeout=payload['timeout'], max_calls=1,
            reasoning_in_output=payload['reasoning_in_output'])
        text = asyncio.run(adapter.invoke(scope, payload['messages'], output_cap=payload['max_tokens']))
    except Exception as exc:
        error = type(exc).__name__  # never serialize exception messages/headers
        cause = exc
        for _ in range(5):
            code = getattr(cause, 'status_code', None)
            if type(code) is int:
                error_fields['http_status'] = code
            if cause.__cause__ is None:
                break
            cause = cause.__cause__
        error_fields['cause_type'] = type(cause).__name__
    usage = None
    for line in events.getvalue().splitlines():
        event = json.loads(line)
        if event['event'] == 'llm_usage':
            usage = event['raw_usage']
    return dict(content=text, usage_metadata=usage, error_type=error, **error_fields)


def verify(payload):
    from src.coding import snapshot
    from src.verification import IsolatedRunner
    with tempfile.TemporaryDirectory(prefix='live-verification-') as directory:
        workspace = Path(directory) / 'workspace'
        shutil.copytree('/input', workspace)
        before = snapshot(workspace)
        result = IsolatedRunner(isolated=True, timeout=payload.get('timeout', 15))(workspace, payload['entry'])
        intact = snapshot(workspace) == before
        return dict(passed=result.passed and intact,
                    reason=result.reason if intact else 'input_mutation',
                    diagnostic=result.diagnostic[-4096:])


if __name__ == '__main__':
    try:
        payload = json.loads(sys.stdin.read(4 * 1024 * 1024))
        result = model(payload) if sys.argv[1] == 'model' else verify(payload)
    except Exception as exc:
        result = dict(error_type=type(exc).__name__)
    print(json.dumps(result))
