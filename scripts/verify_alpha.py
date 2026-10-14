"""Read-only checks of saved alpha evidence, history and retained Git blobs."""
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
from pathlib import Path
from app.permanent import parse_document
from app.journal import expand_history


def audit(folder):
    checks = []
    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    def read(name):
        return json.loads((folder / name).read_text(encoding='utf-8'))
    report = read('report.json')
    check('Actual alpha GUI run', report.get('ok') and not report.get('errors'))
    first, second = read('permanent.json'), read('reexport.json')
    state = parse_document(first)
    check('Exact roundtrip', state == parse_document(second))
    check('Full source history archived', any(a['history'] == first['history'] for a in second['importedHistory']))
    rows = list(expand_history(first))
    check('Journal latest equals graph', rows[-1]['state'] == state)
    ids = report['ids']
    children = lambda ident: {e['to'] for e in state['edges'] if e['from'] == ident and e['role'] == 'component'}
    check('alpha1 preserves nested alpha2', children(ids['a1']) == {ids['part'], ids['a2']})
    check('alpha2 preserves direct rod/head', children(ids['a2']) == {ids['rod'], ids['head']})
    check('alpha3 references same alpha2', children(ids['a3']) == {ids['a2']})
    check('No identity copies', len({n['id'] for n in state['nodes']}) == len(state['nodes']))
    check('Whole and head relations are separate', {e['to'] for e in state['edges'] if e['from'] == ids['a1'] and e['role'] == 'relation'} == {ids['whole']} and any(e['from'] == ids['head'] and e['to'] == ids['turn'] and e['role'] == 'relation' for e in state['edges']))
    check('Designation is external', any(d['text'] == 'винт' and d['target'] == ids['a1'] for d in state['designations']) and not any(d['target'] == ids['a2'] for d in state['designations']))
    check('Component publications are separate', all(set(p.get('componentIds', [])) <= {e['id'] for e in state['edges'] if e['role'] == 'component'} for p in state['definitionPublications'].values()))
    check('Seven atomic HTTP refusals recorded', len(report['negative']) == 7 and all(n['status'] == 400 for n in report['negative']))
    for name in ('context', 'canvas', 'designations', 'permanent', 'workspace-views', 'builder'):
        regression = read('regression-' + name + '.json')
        check('M007–M012 GUI: ' + name, regression.get('ok') and not regression.get('errors') and not regression.get('failure'))
    retained = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '09cc89b', '--', 'archive', 'data/experiments', 'data/fixtures', 'docs/research']).decode().splitlines()
    for name in [*retained, 'app/store.py', 'app/composition.py', 'app/journal.py', 'app/designations.py', 'app/definitions.py', 'app/dictionary.py']:
        original = subprocess.check_output(['git', 'show', '09cc89b:' + name])
        check('Retained file: ' + name, hashlib.sha256(original).digest() == hashlib.sha256(Path(name).read_bytes().replace(b'\r\n', b'\n')).digest() if name.endswith(('.py', '.md', '.json')) else hashlib.sha256(original).digest() == hashlib.sha256(Path(name).read_bytes()).digest())
    files = [{'name': p.relative_to(folder).as_posix(), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.rglob('*')) if p.is_file() and p.name != 'verification.json']
    result = {'result': 'passed', 'base': '09cc89b', 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'checks': checks, 'files': files}
    (folder / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f'{len(checks)} alpha evidence checks passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, default=Path('docs/manual/evidence/alpha'))
    audit(parser.parse_args().evidence)
