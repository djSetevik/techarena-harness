"""Small live sample run using the validated image and a shared host ledger.

The controller executes only trusted harness code on the host. Model-supplied
Python is executed exclusively by network-none workers without proxy env.
"""
import argparse
import asyncio
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docs.codex.tools.prepare_samples import prepare
from src.budget import BudgetManager, limit_units
from src.oj_adapter import OJAdapter
from src.telemetry import Recorder
from src.verification import Verification
from src.coding import contract
from src.model_routing import add_arguments as add_routing_arguments, from_arguments as routing_from_arguments


def load_proxy_config(path):
    raw = json.loads(path.read_text())
    values = {}
    for name in ('LLM_BASE_URL', 'LLM_API_KEY'):
        value = raw.get(name) if isinstance(raw, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Authorized API file lacks required proxy fields')
        values[name] = value.strip()
    os.environ.update(values)


class ContainerWorkers:
    def __init__(self, budget, *, model, network='bridge', reasoning_in_output=True, allowed_models=None,
                 image='techarena:validated'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', network):
            raise ValueError('Invalid Docker network name')
        self.budget, self.model_name = budget, model
        self.network, self.reasoning_in_output = network, reasoning_in_output
        self.allowed_models = frozenset((model,)) if allowed_models is None else frozenset(allowed_models)
        self.image = image
        self.errors = []

    def command(self, mode, payload, *, workspace=None):
        name = 'techarena-live-' + uuid.uuid4().hex[:12]
        command = ['docker', 'run', '--pull', 'never', '--rm', '-i', '--name', name,
            '--read-only', '--network', self.network if mode == 'model' else 'none',
            '--tmpfs', '/tmp:rw,size=512m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--user', '10001:10001', '--cpus', '2', '--memory', '4g', '--pids-limit', '128',
            '-e', 'HOME=/tmp', '--mount', f'type=bind,src={ROOT / "tools/live_worker.py"},dst=/checks/worker.py,readonly']
        environment = {'PATH': os.defpath}
        if mode == 'model':
            for key in ('LLM_BASE_URL', 'LLM_API_KEY'):
                if not os.environ.get(key):
                    raise ValueError(f'{key} is missing; no request sent')
                environment[key] = os.environ[key]
                command.extend(['-e', key])  # values never appear in argv/logs
        else:
            workspace.chmod(0o755)
            command.extend(['--mount', f'type=bind,src={workspace},dst=/input,readonly'])
        command.extend(['--entrypoint', 'python', self.image, '/checks/worker.py', mode])
        try:
            result = subprocess.run(command, input=json.dumps(payload), env=environment,
                capture_output=True, text=True, timeout=payload.get('timeout', 50) + 8)
            if result.returncode:
                raise RuntimeError('Container worker failed; captured output is not exposed')
            return json.loads(result.stdout)
        finally:
            # Clean up only this owned worker if the attached Docker CLI times
            # out/cancels; no untracked model request may keep running.
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(['docker', 'kill', name], env={'PATH': os.defpath},
                               capture_output=True, timeout=1, check=False)

    async def invoke(self, *, messages, model, max_tokens, temperature, timeout):
        if model not in self.allowed_models:
            raise ValueError('Fixed-model violation')
        reservation = self.budget.snapshot()['reserved_units']
        if reservation <= 0:
            raise ValueError('Model worker requires the shared ledger reservation')
        # This evaluation is intentionally serial. A bounded synchronous Docker
        # RPC avoids inheriting controller threads into later verification work.
        result = self.command('model', dict(messages=messages, model=model,
            max_tokens=max_tokens, timeout=max(1, timeout - 10), reservation_units=reservation,
            reasoning_in_output=self.reasoning_in_output))
        if result.get('error_type'):
            self.errors.append({key: result[key] for key in ('error_type', 'cause_type', 'http_status') if key in result})
        return SimpleNamespace(content=result.get('content'), usage_metadata=result.get('usage_metadata'))

    def verify(self, workspace, entry):
        result = self.command('verify', dict(entry=entry, timeout=15), workspace=workspace)
        if 'passed' not in result:
            return Verification(False, 'verification_worker_error')
        return Verification(result['passed'], result['reason'], result.get('diagnostic', ''))


def grade(output, workers):
    """External grading, only after all solving; labels never reach a worker."""
    labels = json.loads((output / 'evaluation/official_answers.json').read_text())
    manifest = json.loads((output / 'fixture_manifest.json').read_text())
    results, reward, allowed = {}, 0, set()
    for name, label in labels.items():
        directory = output / 'tasks' / name
        answer = directory / 'answer.txt'
        correct = False
        if label['task_type'] == 'coding':
            raw = json.loads((directory / 'task.json').read_text())
            source, entry = contract(raw['instruction'])
            allowed.add(f'{name}/workspace/{source}')
            if answer.is_file() and answer.read_text().strip() == 'DONE':
                correct = workers.verify(directory / 'workspace', entry).passed
        elif answer.is_file():
            text = answer.read_text().strip()
            if label['check'] == 'exact_int':
                correct = bool(re.fullmatch(r'[+-]?\d+', text)) and int(text) == int(label['expected'])
            elif label['check'] == 'exact_str':
                correct = text == str(label['expected']).strip()
        results[name] = dict(task_type=label['task_type'], passed=correct,
                             answer_present=answer.is_file())
        if correct:
            reward += label['reward']
    for name, digest in manifest['runtime_files_sha256'].items():
        if name not in allowed:
            if hashlib.sha256((output / 'tasks' / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Protected sample input changed')
    return dict(results=results, verified_reward=reward, protected_inputs_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    parser.add_argument('--api-config', type=Path, help='Explicitly authorized JSON with proxy environment fields')
    parser.add_argument('--model', choices=['qwen3.8-27b', 'qwen3.6-35b-a3b'])
    add_routing_arguments(parser)
    parser.add_argument('--reasoning-usage', choices=['included', 'separate'], required=True)
    parser.add_argument('--network', default='bridge')
    parser.add_argument('--image', default='techarena:validated')
    parser.add_argument('--budget', default='10000')
    parser.add_argument('--max-calls', type=int, default=4)
    args = parser.parse_args()
    if args.model_mode == 'complexity' and args.model:
        parser.error('--model is fixed-mode only; use --easy-model/--hard-model for routing')
    try:
        policy = routing_from_arguments(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.api_config:
        try:
            load_proxy_config(args.api_config)
        except ValueError as exc:
            parser.error(str(exc))
    total_units = limit_units(args.budget)
    # Until the real proxy usage schema is observed, keep half the requested
    # cap untouched. This also bounds a possible separate reasoning counter
    # when it is no greater than the reported output counter.
    budget = BudgetManager(total_units, safety_units=total_units // 2)
    if not 0 < budget.limit <= 100000 or not 0 < args.max_calls <= 4:
        parser.error('Live sample cap: BUDGET<=10000 output tokens, max_calls<=4')
    missing = [key for key in ('LLM_BASE_URL', 'LLM_API_KEY') if not os.environ.get(key)]
    if missing:
        parser.error('Missing proxy environment: ' + ', '.join(missing) + '; no paid calls sent')
    output = args.out.absolute()
    prepare(ROOT / 'docs/codex/materials/original/task-dir.zip', output)
    with (output / 'events.jsonl').open('x') as stream:
        recorder = Recorder(stream)
        workers = ContainerWorkers(budget, model=policy.primary_model, network=args.network,
                                   allowed_models=policy.allowed_models,
                                   image=args.image,
                                   reasoning_in_output=args.reasoning_usage == 'included')
        adapter = OJAdapter(budget, recorder, model_name=policy.primary_model, model=workers,
                            allowed_models=policy.allowed_models,
                            max_calls=args.max_calls,
                            reasoning_in_output=args.reasoning_usage == 'included')
        import run_agent
        previous = signal.signal(signal.SIGTERM, run_agent.stop)
        try:
            status = run_agent.run(SimpleNamespace(tasks_dir=output / 'tasks', max_llm_calls=args.max_calls),
                                   budget, recorder, adapter=adapter, verifier=workers.verify)
        except (run_agent.StopRequested, KeyboardInterrupt) as exc:
            status = 128 + (exc.signum if isinstance(exc, run_agent.StopRequested) else signal.SIGINT)
            recorder.emit('run_interrupted', 'run', **budget.snapshot())
        finally:
            signal.signal(signal.SIGTERM, previous)
    report = dict(model=policy.primary_model, model_mode=policy.mode,
                  easy_model=policy.easy_model, hard_model=policy.hard_model,
                  routing_threshold=policy.threshold, max_calls=args.max_calls, calls=adapter.calls,
                  reasoning_usage=args.reasoning_usage, safety_units=budget.safety,
                  worker_errors=workers.errors, **budget.snapshot())
    report['external_grading'] = grade(output, workers) if not status else {'status': 'NOT RUN: interrupted'}
    (output / 'live_summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return status if adapter.calls and not budget.unresolved else 1


if __name__ == '__main__':
    raise SystemExit(main())
