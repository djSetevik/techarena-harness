"""Two bounded live routing probes, not a model quality benchmark.

Requires owner-authorized proxy config. No task program is executed. Synthetic
expectations are used only after the runtime returns, never in runtime inputs.
"""
import argparse
import json
import signal
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_agent
from src.budget import BudgetManager
from src.model_routing import ModelRouting
from src.oj_adapter import OJAdapter
from src.telemetry import Recorder
from tools.live_evaluate import ContainerWorkers, load_proxy_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-config', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--image', default='techarena:routing')
    args = parser.parse_args()
    load_proxy_config(args.api_config)
    if args.out.exists():
        parser.error('Use a fresh probe output directory')
    args.out.mkdir(parents=True)
    cases = [('alpha', 'A week has seven days. How many days are in two weeks?', '14'),
             ('beta', 'Evaluate (2+3)*(7-4)+8*2-9/3.', '28')]
    for name, instruction, _ in cases:
        directory = args.out / 'tasks' / name
        directory.mkdir(parents=True)
        (directory / 'task.json').write_text(json.dumps(dict(task_id=name, task_type='math',
            instruction=instruction, reward=1, check='exact_int')))
    budget = BudgetManager(20000)  # total test cap 2000 output-equivalent tokens
    policy = ModelRouting(mode='complexity')
    with (args.out / 'events.jsonl').open('x') as stream:
        recorder = Recorder(stream)
        workers = ContainerWorkers(budget, model=policy.primary_model,
            allowed_models=policy.allowed_models, image=args.image)
        adapter = OJAdapter(budget, recorder, model_name=policy.primary_model, model=workers,
                            allowed_models=policy.allowed_models, max_calls=2)
        interrupted = False
        previous = signal.signal(signal.SIGTERM, run_agent.stop)
        try:
            run_agent.run(SimpleNamespace(tasks_dir=args.out / 'tasks', max_llm_calls=2,
                                         model_mode='complexity'), budget, recorder, adapter=adapter)
        except (run_agent.StopRequested, KeyboardInterrupt):
            interrupted = True
            recorder.emit('run_interrupted', 'run', **budget.snapshot())
        finally:
            signal.signal(signal.SIGTERM, previous)
    correct = {}
    for name, _, expected in cases:
        answer = args.out / 'tasks' / name / 'answer.txt'
        correct[name] = answer.is_file() and answer.read_text().strip() == expected
    events = [json.loads(line) for line in (args.out / 'events.jsonl').read_text().splitlines()]
    decisions = [{key: e[key] for key in ('scope', 'model', 'complexity', 'score', 'reason')}
                 for e in events if e['event'] == 'model_selected']
    requests = [e['model'] for e in events if e['event'] == 'llm_request']
    summary = dict(purpose='Connectivity/routing probes only, not comparative quality',
        decisions=decisions, requests=requests, verified=correct, worker_errors=workers.errors,
        calls=adapter.calls, **budget.snapshot())
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))
    return 0 if not interrupted and all(correct.values()) and set(requests) == policy.allowed_models and not budget.unresolved else 1


if __name__ == '__main__':
    raise SystemExit(main())
