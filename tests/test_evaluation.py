import json
from pathlib import Path
import unittest
import tempfile

from tools.evaluate_offline import aggregate, evaluate
from tools.generate_synthetic import generate


class Evaluation(unittest.TestCase):
    def test_generator_deterministic_parent_split_labels_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = [generate(root / name, seed=42, instances=1) for name in ('one', 'two')]
            self.assertEqual(manifests[0], manifests[1])
            one, two = root / 'one', root / 'two'
            files = {p.relative_to(one): p.read_bytes() for p in one.rglob('*') if p.is_file()}
            self.assertEqual(files, {p.relative_to(two): p.read_bytes() for p in two.rglob('*') if p.is_file()})
            self.assertFalse(set(manifests[0]['train_parents']) & set(manifests[0]['test_parents']))
            labels = json.loads((one / 'evaluation/labels.json').read_text())
            for path in (one / 'tasks').glob('*/task.json'):
                raw = json.loads(path.read_text())
                self.assertNotIn('expected', raw)
                self.assertNotIn('split', raw)
                self.assertNotIn('parent_template', raw)
            parents = {}
            for label in labels.values():
                parents.setdefault(label['parent_template'], set()).add(label['split'])
                if label['feasibility'] == 'UNSOLVABLE':
                    self.assertEqual(len(set(label['provenance']['possible_answers'])), 2)
                    self.assertTrue(label['provenance']['proof'])
            self.assertTrue(all(len(splits) == 1 for splits in parents.values()))
            self.assertEqual(len(parents), 3)  # aliases/prose/formulas are variants, not new parents
            with self.assertRaises(ValueError):
                generate(one)

    def test_external_evaluation_ablations(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / 'corpus'
            generate(corpus, instances=1)
            full = evaluate(corpus, split='train')
            no_gate = evaluate(corpus, split='train', ablation='no_gate')
            no_solve = evaluate(corpus, split='train', ablation='no_deterministic')
            self.assertGreater(full['verified_reward'], 0)
            self.assertEqual(full['false_skip_count'], 0)
            self.assertEqual(full['false_unsolvable_count'], 0)
            self.assertEqual(full['verified_reward'], no_gate['verified_reward'])
            self.assertEqual(no_solve['verified_reward'], 0)
            for result in (full, no_gate, no_solve):
                self.assertEqual(result['llm_requests'], 0)
                self.assertEqual(result['actual_units'], 0)
                self.assertEqual(result['unresolved_units'], 0)
                self.assertIsNone(result['cost_mae_output_tokens'])
                self.assertEqual(result['cost_observations'], 0)
                self.assertTrue(result['inputs_unchanged'])
                self.assertEqual(len(result['runtime_sha256']), 64)

    def test_metrics_known_cost_and_false_skip(self):
        labels = {'positive': dict(feasibility='SOLVABLE', reward=5, expected='3', check='exact_int'),
                  'skipped': dict(feasibility='SOLVABLE', reward=7, expected='4', check='exact_int')}
        events = [dict(event='task_prediction', scope='/tmp/positive', expected_units=10, high_units=30),
                  dict(event='task_prediction', scope='/tmp/skipped', expected_units=10, high_units=30),
                  dict(event='feasibility', scope='/tmp/positive', status='UNKNOWN'),
                  dict(event='feasibility', scope='/tmp/skipped', status='UNSOLVABLE'),
                  dict(event='task_end', scope='/tmp/skipped', skip_reason='proven_unsolvable'),
                  dict(event='llm_request', scope='/tmp/positive'),
                  dict(event='llm_usage', scope='/tmp/positive', cost_units=20)]
        metrics = aggregate(labels, events, {'positive': '3'}, 0.1)
        self.assertEqual(metrics['verified_reward'], 5)
        self.assertEqual(metrics['false_skip_count'], 1)
        self.assertEqual(metrics['false_skip_reward'], 7)
        self.assertEqual(metrics['cost_mae_output_tokens'], 1)
        self.assertEqual(metrics['mean_underprediction_output_tokens'], 1)
        self.assertEqual(metrics['high_estimate_coverage'], 1)
        self.assertEqual(metrics['cost_observations'], 1)
        events.append(dict(event='unresolved_usage', scope='/tmp/positive', units=30))
        self.assertIsNone(aggregate(labels, events, {'positive': '3'}, 0.1)['cost_mae_output_tokens'])

    def test_packaging_static_runtime_only(self):
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / 'Dockerfile').read_text()
        self.assertNotIn('COPY . ', dockerfile)
        self.assertIn('COPY src/ /app/src/', dockerfile)
        self.assertIn('USER 10001:10001', dockerfile)
        self.assertIn('HOME=/tmp', dockerfile)
        self.assertEqual((root / 'requirements.txt').read_text().strip(), 'openjiuwen==0.1.19')
        ignore = (root / '.dockerignore').read_text().splitlines()
        self.assertIn('**', ignore)
        self.assertEqual({line for line in ignore if line.startswith('!')},
                         {'!requirements.txt', '!constraints.txt', '!run_agent.py', '!src/', '!src/*.py', '!tools/', '!tools/install_locked.py'})
        # Enumerate only runtime sources; do not inspect .env or local configs.
        self.assertTrue(all(not p.is_symlink() for p in (root / 'src').rglob('*.py')))


if __name__ == '__main__':
    unittest.main()
