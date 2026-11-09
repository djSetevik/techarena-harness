import dataclasses
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.answer_writer import save_answer
from src.domain import Status as S
from src.feasibility import data, detect, search
from src.task_loader import load_task

ROOT = Path(__file__).resolve().parents[1]
CLOSED = 'Closed KB schema v1. '
BORN = 'In which year was Ada born?'
HQ = "In which city is the headquarters of Ada's employer?"
CSV = "The file orders.csv. How many units of product 'widget' were sold in months 5 through 6 inclusive?"


class Offline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = self.root / 'workspace'
        (self.ws / 'kb').mkdir(parents=True)

    def kb(self, text, name='a.md'):
        (self.ws / 'kb' / name).write_text(text)

    def csv(self, text):
        (self.ws / 'orders.csv').write_text(text)
        return data(CSV, self.ws)

    def test_F01_closed_missing(self):
        self.kb('# Ada\nEmployer: Firm\n')
        result = search(CLOSED + BORN, self.ws)
        self.assertEqual(result.status, S.UNSOLVABLE)
        self.assertTrue(result.scope_complete)
        self.assertEqual(result.evidence[0].possible_answers, ('1900', '1901'))
        self.assertFalse((self.root / 'answer.txt').exists())
        self.assertEqual(search(BORN, self.ws).status, S.UNKNOWN)

    def test_F02_other_file(self):
        self.kb('# Ada\nEmployer: Firm\n')
        self.kb('# Ada\nBorn: 1980\n', 'other.md')
        self.assertEqual(search(CLOSED + BORN, self.ws).answer, '1980')

    def test_F03_free_text(self):
        self.kb('# Ada\nAda was born in 1980.\n')
        self.assertEqual(search(CLOSED + BORN, self.ws).status, S.UNKNOWN)

    def test_F04_edge_aliases(self):
        self.kb('# Ada\nBorn: 1980\n# Firm\nHeadquarters: City\n')
        self.assertEqual(search(CLOSED + HQ, self.ws).status, S.UNSOLVABLE)
        self.kb('# Augusta\nAliases: Ada\nEmployer: Firm Alias\n# Firm\nAliases: Firm Alias\nHeadquarters: City\n')
        self.assertEqual(search(CLOSED + HQ, self.ws).answer, 'City')

    def test_F05_conflict(self):
        self.kb('# Ada\nBorn: 1980\nBorn: 1981\n')
        result = search(CLOSED + BORN, self.ws)
        self.assertEqual(result.status, S.UNSOLVABLE)
        self.assertEqual(set(result.evidence[0].possible_answers), {'1980', '1981'})
        self.assertIsNone(search(BORN, self.ws).answer)

    def test_F05_intermediate_conflict_can_have_unique_answer(self):
        self.kb('# Ada\nEmployer: Firm\nEmployer: Other\n'
                '# Firm\nHeadquarters: City\n# Other\nHeadquarters: City\n')
        result = search(CLOSED + HQ, self.ws)
        self.assertEqual(result.status, S.UNKNOWN)
        self.assertEqual(result.reason_code, 'AMBIGUOUS_INTERMEDIATE_FACT')

    def test_F04_employer_aliases_are_not_insufficiency(self):
        self.kb('# Ada\nEmployer: Firm\nEmployer: Alias\n'
                '# Firm\nAliases: Alias\nHeadquarters: City\n')
        self.assertNotEqual(search(CLOSED + HQ, self.ws).status, S.UNSOLVABLE)

    def test_F06_priority_unsupported(self):
        self.kb('# Ada\nBorn: 1980\nBorn: 1981\nPriority: latest record\n')
        self.assertEqual(search(CLOSED + BORN + ' Use latest record.', self.ws).status, S.UNKNOWN)

    def test_F07_scan_limit(self):
        self.kb('# Ada\nBorn: 1980\n')
        for options in ({'max_files': 0}, {'max_bytes': 1}):
            result = search(CLOSED + BORN, self.ws, **options)
            self.assertEqual(result.status, S.UNKNOWN)
            self.assertFalse(result.scope_complete)

    def test_F08_empty_sum(self):
        self.assertEqual(self.csv('product,month,units\nother,5,3\n').answer, '0')

    def test_F09_missing_units(self):
        result = self.csv('product,month,units\nwidget,5,\nwidget,6,4\n')
        self.assertEqual(result.status, S.UNSOLVABLE)
        self.assertEqual(result.evidence[0].possible_answers, ('4', '5'))

    def test_F10_recovery(self):
        self.csv('product,month,quantity\nwidget,5,3\n')
        self.assertEqual(data(CSV + ' Formula: units = quantity.', self.ws).status, S.UNKNOWN)

    def test_F11_irrelevant_missing(self):
        self.assertEqual(self.csv('product,month,units,price\nother,5,,\nwidget,2,,\nwidget,5,3,\n').answer, '3')

    def test_F12_malformed_io(self):
        for text in ('product;month;units\nwidget;5;3\n', 'product,month,units\nwidget,5,"unclosed',
                     'product,month,units\nwidget,5,4,extra\n'):
            self.assertEqual(self.csv(text).status, S.UNKNOWN)
        with patch('src.feasibility.read_text', side_effect=PermissionError):
            self.assertEqual(data(CSV, self.ws).status, S.UNKNOWN)

    def task(self, **overrides):
        raw = dict(task_id='irrelevant', task_type='search', instruction=BORN, reward=1, check='exact_str')
        raw.update(overrides)
        path = self.root / 'task.json'
        path.write_text(json.dumps(raw))
        return load_task(path, self.root)

    def test_A03_A04_labels_identifiers_reward(self):
        self.kb('# Ada\nBorn: 1980\n')
        first = self.task()
        second = self.task(expected='fake', task_id='changed', reward=999)
        self.assertNotIn('expected', dataclasses.asdict(second))
        self.assertEqual(detect(first), detect(second))
        self.kb('# Renamed Person\nBorn: 1980\n', 'a.md')
        self.assertEqual(search(BORN.replace('Ada', 'Renamed Person'), self.ws).answer, '1980')

    def test_A05_writer(self):
        self.task()
        for answer in ('', '  '):
            with self.assertRaises(ValueError):
                save_answer(self.root, answer)
        save_answer(self.root, '1980')
        self.assertEqual((self.root / 'answer.txt').read_text(), '1980\n')
        self.assertEqual((self.root / 'answer.txt').stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.ws / 'answer.txt').exists())
        with self.assertRaises(FileExistsError):
            save_answer(self.root, 'changed')
        self.assertEqual(list(self.root.glob('.answer-*')), [])

    def test_writer_failure_cleanup(self):
        self.task()
        with patch('src.answer_writer.os.link', side_effect=OSError):
            with self.assertRaises(OSError):
                save_answer(self.root, 'answer')
        self.assertFalse((self.root / 'answer.txt').exists())
        self.assertEqual(list(self.root.glob('.answer-*')), [])

    def test_A07_scoped_and_no_mutation(self):
        self.kb('# Ada\nBorn: 1980\n')
        other = self.root / 'other'
        (other / 'kb').mkdir(parents=True)
        (other / 'kb' / 'a.md').write_text('# Ada\nBorn: 1990\n')
        before = (self.ws / 'kb' / 'a.md').read_bytes()
        self.assertEqual(search(BORN, self.ws).answer, '1980')
        self.assertEqual(search(BORN, other).answer, '1990')
        self.assertEqual((self.ws / 'kb' / 'a.md').read_bytes(), before)

    def test_paths_and_reward(self):
        self.kb('# Ada\nBorn: 1980\n')
        (self.ws / 'kb' / 'escape.md').symlink_to(self.root / 'task.json')
        self.assertEqual(search(BORN, self.ws).status, S.UNKNOWN)
        for reward in (-1, float('inf'), float('nan'), True):
            with self.assertRaises(ValueError):
                self.task(reward=reward)

    def test_task_metadata_cannot_link_to_another_task(self):
        self.task()
        other = self.root / 'other'
        other.mkdir()
        (other / 'task.json').symlink_to(self.root / 'task.json')
        with self.assertRaises(ValueError):
            load_task(other / 'task.json', self.root)
        linked = self.root / 'linked'
        linked.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            load_task(linked / 'task.json', self.root)

    def test_A01_A02_A06_integration(self):
        from docs.codex.tools.prepare_samples import prepare
        source = ROOT / 'docs/codex/materials/original/task-dir.zip'
        digest = hashlib.sha256(source.read_bytes()).digest()
        for index in range(2):
            output = self.root / f'fixtures{index}'
            prepare(source, output)
            tasks = output / 'tasks'
            paths = list(tasks.glob('*/task.json'))
            self.assertEqual(len(paths), 8)
            for path in paths:
                self.assertNotIn('expected', json.loads(path.read_text()))
                self.assertNotEqual(detect(load_task(path, tasks)).status, S.UNSOLVABLE)
            self.assertEqual(list(tasks.rglob('answer.txt')), [])
            inputs = {p: p.read_bytes() for p in tasks.rglob('*') if p.is_file()}
            # Network and execution of task programs are forbidden in this run.
            import run_agent
            with patch.object(sys, 'argv', ['run_agent.py', '--tasks-dir', str(tasks), '--max-llm-calls', '0']), \
                 patch('src.verification.subprocess.Popen', side_effect=AssertionError('task execution')), \
                 patch('src.oj_adapter.OJAdapter.invoke', side_effect=AssertionError('LLM call')), \
                 patch('socket.socket', side_effect=AssertionError('network')):
                self.assertEqual(run_agent.main(), 0)
            self.assertTrue(all(p.read_bytes() == blob for p, blob in inputs.items()))
            self.assertEqual(len(list(tasks.glob('*/answer.txt'))), 6)
            self.assertEqual(list(tasks.glob('*/workspace/answer.txt')), [])
            graded = subprocess.run([sys.executable, str(ROOT / 'docs/codex/tools/grade_non_coding.py'),
                                     '--tasks-dir', str(tasks), '--labels', str(output / 'evaluation/official_answers.json')],
                                    capture_output=True, text=True, check=True)
            self.assertIn('verified sample reward: 16', graded.stdout)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)


if __name__ == '__main__':
    unittest.main()
