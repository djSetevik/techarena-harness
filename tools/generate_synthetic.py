"""Seeded development corpus. Labels/provenance stay outside runtime tasks.

Each parent template, including all generated instances and paired variants,
belongs to one split. No mutation is labelled impossible without two worlds.
"""
import argparse
import json
from pathlib import Path
import random


FAMILIES = ('born', 'employer', 'alias', 'csv_sum', 'csv_empty', 'csv_formula', 'born_prose')
PARENTS = {'born': 'birth_query', 'born_prose': 'birth_query',
           'employer': 'employer_hq_query', 'alias': 'employer_hq_query',
           'csv_sum': 'filtered_units_sum', 'csv_empty': 'filtered_units_sum',
           'csv_formula': 'filtered_units_sum'}


def generate(output: Path, *, seed=2026, instances=2):
    if output.exists() or output.is_symlink():
        raise ValueError('Use a fresh output directory')
    if not 1 <= instances <= 100:
        raise ValueError('instances must be 1..100 per parent template')
    rng = random.Random(seed)
    parents = sorted(set(PARENTS.values()))
    rng.shuffle(parents)
    train = set(parents[:2])
    records = []
    for family in FAMILIES:
        for instance in range(instances):
            year, units = rng.randint(1900, 2020), rng.randint(1, 90)
            person = f'Person {rng.randrange(10**8)}'
            firm, city = f'Firm {rng.randrange(10**8)}', f'City {rng.randrange(10**8)}'
            closed = 'Closed KB schema v1. '
            for variant in range(2):
                files, answer, worlds = {}, None, []
                feasible = 'SOLVABLE'
                if family in {'born', 'born_prose'}:
                    instruction = closed + f'In which year was {person} born?'
                    text = f'# {person}\nBorn: {year}\n'
                    if variant:
                        if family == 'born':
                            text = f'# {person}\nEmployer: {firm}\n'
                            feasible, worlds = 'UNSOLVABLE', [str(year), str(year + 1)]
                        else:
                            text = f'# {person}\n{person} was born in {year}.\n'
                    if feasible == 'SOLVABLE':
                        answer = str(year)
                    files['kb/facts.md'] = text
                    proof = 'Scalar Born missing in closed KB; complete it with either year.'
                elif family in {'employer', 'alias'}:
                    instruction = closed + f"In which city is the headquarters of {person}'s employer?"
                    target = firm if family == 'employer' else 'Company Alias'
                    text = f'# {person}\nEmployer: {target}\n# {firm}\n'
                    if family == 'alias':
                        text += 'Aliases: Company Alias\n'
                    if not variant:
                        text += f'Headquarters: {city}\n'
                        answer = city
                    else:
                        feasible, worlds = 'UNSOLVABLE', [city, city + ' Other']
                    files['kb/facts.md'] = text
                    proof = 'Employer resolves uniquely; missing closed Headquarters admits two cities.'
                else:
                    instruction = "The file orders.csv. How many units of product 'widget' were sold in months 5 through 6 inclusive?"
                    text = f'product,month,units\nwidget,5,{units}\nother,6,\n'
                    answer = str(units)
                    if family == 'csv_empty':
                        text, answer = 'product,month,units\nother,5,\n', '0'
                    if variant and family != 'csv_formula':
                        text = 'product,month,units\nwidget,5,\nother,6,\n'
                        feasible, worlds, answer = 'UNSOLVABLE', ['0', '1'], None
                    if variant and family == 'csv_formula':
                        text = f'product,month,quantity\nwidget,5,{units}\n'
                        instruction += ' Formula: units = quantity.'
                    files['orders.csv'] = text
                    proof = 'Relevant blank units: completions 0 and 1 produce different sums; no recovery formula.'
                index = len(records)
                directory = f'case_{index:04d}'
                task = dict(task_id=f'opaque-{rng.randrange(10**12)}',
                            task_type='data_analysis' if family.startswith('csv') else 'search',
                            instruction=instruction, reward=rng.randint(1, 5),
                            check='exact_int' if family.startswith('csv') else 'exact_str')
                label = dict(parent_template=PARENTS[family], variant_template=family,
                             parent_instance=instance, paired_variant=variant,
                             split='train' if PARENTS[family] in train else 'test', feasibility=feasible,
                             expected=answer, reward=task['reward'], check=task['check'],
                             provenance=dict(generator='paired-v1', seed=seed,
                                 proof=proof if feasible == 'UNSOLVABLE' else 'Answer computed from supplied complete facts/formula.',
                                 possible_answers=worlds))
                records.append((directory, task, files, label))
    # Build everything before writing, and never overwrite an earlier corpus.
    output.mkdir(parents=True, exist_ok=False)
    labels = {}
    for directory, task, files, label in records:
        root = output / 'tasks' / directory
        root.mkdir(parents=True)
        (root / 'task.json').write_text(json.dumps(task, indent=2) + '\n')
        for name, text in files.items():
            target = root / 'workspace' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        labels[directory] = label
    evaluation = output / 'evaluation'
    evaluation.mkdir()
    (evaluation / 'labels.json').write_text(json.dumps(labels, indent=2) + '\n')
    manifest = dict(generator='paired-v1', seed=seed, instances_per_parent=instances,
                    count=len(records), split_unit='parent_template',
                    train_parents=sorted(train), test_parents=sorted(set(PARENTS.values()) - train),
                    purpose='Synthetic local quality checks, not hidden tasks or real usage traces')
    (evaluation / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--instances', type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(generate(args.out, seed=args.seed, instances=args.instances), indent=2))
