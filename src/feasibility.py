"""Conservative offline analysis for small, explicitly supported local schemas.

Closed KB semantics are opt-in: instruction must contain 'Closed KB schema v1'.
That schema consists solely of headings and scalar fields, with no inference or
priority rules. Unrecognised prose, files, aliases ambiguity or limits => UNKNOWN.
"""
import csv
import io
import re
from pathlib import Path
from src.domain import Evidence, FeasibilityResult as Result, Status, TaskSpec
from src.task_loader import read_text, scoped


def unknown(reason: str, complete: bool = False) -> Result:
    return Result(Status.UNKNOWN, reason, scope_complete=complete)


OUTPUT_SUFFIX = (r'(?:Work only inside the current directory\.\s*)?'
    r'(?:When you are done, write ONLY the final answer to the file answer\.txt '
    r'in the current directory \(for example with bash: echo 42 > answer\.txt\)\.)?')


def covered(instruction, match, prefix, suffix):
    """Only known nonsemantic boilerplate may surround a supported query."""
    return (re.fullmatch(prefix, instruction[:match.start()].strip(), re.I) is not None
            and re.fullmatch(suffix, instruction[match.end():].strip(), re.I) is not None)


def search(instruction: str, workspace: Path, max_files: int = 256,
           max_bytes: int = 2 * 1024 * 1024) -> Result:
    born = re.search(r'In which year was (.+?) born\?', instruction, re.I)
    hq = re.search(r"In which city is the headquarters of (.+?)'s employer\?", instruction, re.I)
    if not (born or hq):
        return unknown('UNSUPPORTED_QUERY')
    if re.search(r'priority|latest|earliest|as of|before|after|as at', instruction, re.I):
        return unknown('UNSUPPORTED_PRIORITY_OR_TIME')
    if not covered(instruction, born or hq,
            r'(?:Closed KB schema v1\.\s*)?(?:The directory kb/ contains a small knowledge base of markdown files\.)?',
            r'(?:Use the file tools or bash \(ls, grep, cat\) to find it\.\s*)?' + OUTPUT_SUFFIX):
        return unknown('UNSUPPORTED_QUERY_CONTEXT')
    closed = 'Closed KB schema v1' in instruction
    try:
        kb = scoped(workspace / 'kb', workspace)
        # Walk without following directory links; any link is unsupported.
        import os
        paths = []
        def walk_error(error):
            raise error
        entries = 0
        for parent, dirs, files in os.walk(kb, onerror=walk_error):
            entries += len(dirs) + len(files)
            if entries > max_files:
                return unknown('RESOURCE_LIMIT')
            if len(Path(parent).relative_to(kb).parts) > 8:
                return unknown('RESOURCE_LIMIT')
            for name in dirs + files:
                if (Path(parent) / name).is_symlink():
                    return unknown('UNSUPPORTED_LINK')
            paths.extend(Path(parent) / name for name in files)
            if len(paths) > max_files:
                return unknown('RESOURCE_LIMIT')
        facts: dict[str, dict[str, set[str]]] = {}
        aliases: dict[str, set[str]] = {}
        size = 0
        provenance = []
        for path in sorted(paths):
            if path.suffix != '.md':
                return unknown('UNSUPPORTED_KB_FILE')
            text = read_text(path, workspace, max_bytes)
            size += len(text.encode('utf-8'))
            if size > max_bytes:
                return unknown('RESOURCE_LIMIT')
            subject = None
            for line in text.splitlines():
                if not line.strip():
                    continue
                heading = re.fullmatch(r'#\s+(.+?)\s*', line)
                field = re.fullmatch(r'([A-Za-z]+):\s*(\S.*?)\s*', line)
                if heading:
                    subject = heading[1]
                    facts.setdefault(subject, {})
                elif subject and field:
                    key, value = field[1].casefold(), field[2]
                    if key not in {'born', 'employer', 'headquarters', 'mentor', 'founded', 'aliases'}:
                        return unknown('UNSUPPORTED_KB_FIELD')
                    if key == 'aliases':
                        for alias in value.split(','):
                            aliases.setdefault(alias.strip(), set()).add(subject)
                    else:
                        facts[subject].setdefault(key, set()).add(value)
                else:
                    return unknown('UNSUPPORTED_KB_PROSE')
            provenance.append(str(path.relative_to(workspace)))
        def canonical(name):
            targets = aliases.get(name, set()) | ({name} if name in facts else set())
            if not targets:
                for key in facts.keys() | aliases.keys():
                    if key.casefold() == name.casefold():
                        targets |= aliases.get(key, set()) | ({key} if key in facts else set())
            return targets
        subject = (born or hq)[1]
        steps = ('born',) if born else ('employer', 'headquarters')
        checked = []
        for step_index, key in enumerate(steps):
            targets = canonical(subject)
            if len(targets) > 1:
                return unknown('AMBIGUOUS_ALIAS', True)
            entity = next(iter(targets)) if targets else None
            values = facts.get(entity, {}).get(key, set())
            checked.append(f'{subject}.{key}')
            if len(values) != 1:
                # Distinct intermediate facts need not produce distinct answers:
                # two employers (or aliases) can have the same headquarters.
                # Until all branches are analysed there is no insufficiency proof.
                if len(values) > 1 and step_index < len(steps) - 1:
                    return unknown('AMBIGUOUS_INTERMEDIATE_FACT', True)
                if not closed:
                    return unknown('MISSING_OR_CONFLICTING_FACT', True)
                answers = tuple(sorted(values)) if values else (('1900', '1901') if key == 'born' else ('City A', 'City B'))
                return Result(Status.UNSOLVABLE, 'AMBIGUOUS_CLOSED_KB',
                    (Evidence(', '.join(provenance),
                              f'{subject}.{key}: {sorted(values)}; closed scalar schema, no inference/priority; '
                              'missing scalar admits two completions (missing employer may lead to two HQ cities)', answers),),
                    True, steps, (f'{subject}.{key}',), tuple(checked))
            subject = next(iter(values))
        if born and re.fullmatch(r'\d{1,4}', subject) is None:
            return unknown('UNSUPPORTED_YEAR_VALUE', True)
        return Result(Status.SOLVABLE, 'SUPPORTED_KB_CHAIN',
                      (Evidence(', '.join(provenance), ' -> '.join(checked)),),
                      True, steps, alternatives_checked=tuple(checked), answer=subject)
    except (OSError, ValueError, UnicodeError):
        return unknown('IO_OR_FORMAT_ERROR')


def data(instruction: str, workspace: Path) -> Result:
    query = re.search(r"How many units of product ['\"]([^'\"]+)['\"] were sold in months (\d+) through (\d+) inclusive\?", instruction, re.I)
    file = re.search(r'\b([\w-]+\.csv)\b', instruction)
    if not query or not file or re.search(r'formula|units\s*=|derive|computed|missing.*(?:zero|ignore)', instruction, re.I):
        return unknown('UNSUPPORTED_QUERY')
    if not covered(instruction, query,
            r'The file [\w-]+\.csv(?: has columns \w+(?:,\s*\w+)*(?: \(\d+ rows\))?)?\.',
            r'(?:Use bash with python3 to compute it\.\s*)?' + OUTPUT_SUFFIX):
        return unknown('UNSUPPORTED_QUERY_CONTEXT')
    lo, hi = int(query[2]), int(query[3])
    if lo > hi:
        return unknown('UNSUPPORTED_RANGE')
    try:
        text = read_text(workspace / file[1], workspace)
        reader = csv.DictReader(io.StringIO(text), strict=True)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not {'product', 'month', 'units'} <= set(headers):
            return unknown('UNSUPPORTED_SCHEMA', True)
        total, missing = 0, []
        for index, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                return unknown('MALFORMED_CSV')
            if not row['product'].strip():
                return unknown('MISSING_FILTER_VALUE', True)
            if row['product'] != query[1]:
                continue
            month = int(row['month'])
            if not lo <= month <= hi:
                continue
            if not row['units'].strip():
                missing.append(index)
            else:
                total += int(row['units'])
        if missing:
            return Result(Status.UNSOLVABLE, 'MISSING_RELEVANT_UNITS',
                (Evidence(file[1], f'rows {missing}: blank units; all other blanks held at 0, '
                          'first blank set to 0 or 1 changes sum', (str(total), str(total + 1))),),
                True, ('product', 'month', 'units'), tuple(f'row {n}.units' for n in missing),
                ('all rows scanned; no supported recovery formula',))
        return Result(Status.SOLVABLE, 'EXACT_SUM', (Evidence(file[1], 'all relevant rows summed'),),
                      True, ('product', 'month', 'units'), answer=str(total))
    except (OSError, ValueError, UnicodeError, csv.Error):
        return unknown('IO_OR_FORMAT_ERROR')


def detect(task: TaskSpec) -> Result:
    if task.task_type == 'math':
        from src.math_solver import analyze
        return analyze(task.instruction)
    if task.task_type == 'search':
        return search(task.instruction, task.workspace)
    if task.task_type == 'data_analysis':
        return data(task.instruction, task.workspace)
    return unknown('UNSUPPORTED_TASK_TYPE')
