"""External evaluator: labels never enter solver input or process arguments."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def runtime_sha256():
    digest = hashlib.sha256()
    for path in sorted([ROOT / 'run_agent.py', *(ROOT / 'src').rglob('*.py')]):
        digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def aggregate(labels, events, answers, elapsed):
    feasibility = {e['scope']: e['status'] for e in events if e['event'] == 'feasibility'}
    forecasts = {e['scope']: e for e in events if e['event'] == 'task_prediction'}
    ended = {e['scope']: e.get('skip_reason') for e in events if e['event'] == 'task_end'}
    scoped_labels = {scope: labels[Path(scope).name] for scope in forecasts}
    actual, unresolved = Counter(), Counter()
    requested = set()
    request_count = 0
    for event in events:
        if event['event'] == 'llm_usage':
            actual[event['scope']] += event['cost_units']
        elif event['event'] == 'unresolved_usage':
            unresolved[event['scope']] += event['units']
        elif event['event'] == 'llm_request':
            requested.add(event['scope'])
            request_count += 1
    checked = correct = reward = zero_reward = 0
    false_skips = false_skip_reward = false_unsolvable = 0
    for scope, label in scoped_labels.items():
        name = Path(scope).name
        if feasibility.get(scope) == 'UNSOLVABLE' and label['feasibility'] == 'SOLVABLE':
            false_unsolvable += 1
        if ended.get(scope) == 'proven_unsolvable' and label['feasibility'] == 'SOLVABLE':
            false_skips += 1
            false_skip_reward += label['reward']
        if name not in answers:
            continue
        checked += 1
        answer, expected = answers[name].strip(), label['expected']
        ok = False
        if label['feasibility'] == 'SOLVABLE':
            if label['check'] == 'exact_int':
                ok = bool(re.fullmatch(r'[+-]?\d+', answer)) and int(answer) == int(expected)
            elif label['check'] == 'exact_str':
                ok = answer == str(expected)
        if ok:
            correct += 1
            reward += label['reward']
            if scope not in requested:
                zero_reward += label['reward']
    observations = [scope for scope in requested if scope in actual and not unresolved[scope]]
    errors = [actual[s] - forecasts[s]['expected_units'] for s in observations]
    n = len(errors)
    return dict(task_count=len(labels), answers=checked, correct_answers=correct,
        verified_reward=reward, zero_llm_reward=zero_reward,
        actual_units=sum(actual.values()), unresolved_units=sum(unresolved.values()),
        actual_output_equivalent_tokens=sum(actual.values()) / 10,
        unresolved_output_equivalent_tokens=sum(unresolved.values()) / 10,
        llm_requests=request_count, false_skip_count=false_skips, false_skip_reward=false_skip_reward,
        false_unsolvable_count=false_unsolvable,
        unknown_count=sum(s == 'UNKNOWN' for s in feasibility.values()),
        unknown_rate=sum(s == 'UNKNOWN' for s in feasibility.values()) / max(1, len(labels)),
        skip_reasons=dict(Counter(reason for reason in ended.values() if reason)),
        cost_observations=n,
        cost_mae_output_tokens=sum(abs(e) for e in errors) / (10 * n) if n else None,
        mean_underprediction_output_tokens=sum(max(0, e) for e in errors) / (10 * n) if n else None,
        high_estimate_coverage=sum(actual[s] <= forecasts[s]['high_units'] for s in observations) / n if n else None,
        wall_time_seconds=elapsed,
        cost_metrics_note='Only sent attempts with known usage; skipped/deterministic tasks are not zero-cost training labels.',
        real_model_traces=False, model_accuracy_metrics_status='NOT RUN: no real model calls')


def evaluate(corpus: Path, *, split='test', ablation='full'):
    labels = json.loads((corpus / 'evaluation/labels.json').read_text())
    manifest = json.loads((corpus / 'evaluation/manifest.json').read_text())
    if set(manifest['train_parents']) & set(manifest['test_parents']):
        raise ValueError('Parent templates leak between splits')
    for label in labels.values():
        if label['split'] not in {'train', 'test'} or label['parent_template'] not in manifest[label['split'] + '_parents']:
            raise ValueError('Label split disagrees with its parent-template assignment')
    labels = {k: v for k, v in labels.items() if v['split'] == split}
    if not labels:
        raise ValueError('No tasks in selected split')
    with tempfile.TemporaryDirectory(prefix='techarena-evaluation-') as directory:
        root = Path(directory)
        tasks = root / 'runtime'
        tasks.mkdir()
        for name in labels:
            if re.fullmatch(r'[A-Za-z0-9_-]+', name) is None:
                raise ValueError('Invalid task directory in labels')
            source = corpus / 'tasks' / name
            if source.is_symlink() or any(p.is_symlink() for p in source.rglob('*')):
                raise ValueError('Linked evaluation input')
            shutil.copytree(source, tasks / name)
        inputs = {p: p.read_bytes() for p in tasks.rglob('*') if p.is_file()}
        if any(p.name == 'answer.txt' for p in inputs):
            raise ValueError('Evaluation requires fresh unanswered inputs')
        for path in tasks.glob('*/task.json'):
            if 'expected' in json.loads(path.read_text()):
                raise ValueError('Runtime labels must be separated first')
        events_path = root / 'events.jsonl'
        # Whole runtime process is guarded. Offline paths never need even an
        # asyncio event loop or a task-program subprocess.
        runner = '''
import runpy
import sys
from unittest.mock import patch
repo, tasks, events, ablation = sys.argv[1:]
sys.path.insert(0, repo)
sys.argv = ['run_agent.py', '--tasks-dir', tasks, '--max-llm-calls', '0',
            '--metrics-path', events, '--offline-ablation', ablation]
with patch('socket.socket', side_effect=AssertionError('network forbidden')), \\
     patch('subprocess.Popen', side_effect=AssertionError('task execution forbidden')):
    runpy.run_path(repo + '/run_agent.py', run_name='__main__')
'''
        started = time.monotonic()
        subprocess.run([sys.executable, '-c', runner, str(ROOT), str(tasks), str(events_path), ablation],
            cwd=root, env={'PATH': os.defpath, 'BUDGET': '0', 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, check=True, timeout=60)
        elapsed = time.monotonic() - started
        if not all(p.read_bytes() == blob for p, blob in inputs.items()):
            raise AssertionError('Runtime mutated input files')
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        if len([e for e in events if e['event'] == 'task_prediction']) != len(labels):
            raise AssertionError('Missing original forecasts')
        answers = {p.parent.name: p.read_text() for p in tasks.glob('*/answer.txt')}
        metrics = aggregate(labels, events, answers, elapsed)
        metrics.update(split=split, ablation=ablation, seed=manifest['seed'],
                       runtime_sha256=runtime_sha256(),
                       source_labels_sha256=hashlib.sha256((corpus / 'evaluation/labels.json').read_bytes()).hexdigest(),
                       inputs_unchanged=True)
        return metrics


def experiment(corpus):
    return dict(purpose='Local synthetic ablations; not the hidden evaluator or live usage',
                runs=[evaluate(corpus, split=split, ablation=mode)
                      for split in ('train', 'test')
                      for mode in ('full', 'no_gate', 'no_deterministic')])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new report path')
    result = experiment(args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))
