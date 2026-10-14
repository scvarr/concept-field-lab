"""Verify presentation evidence without changing a graph or old M013 evidence."""
import hashlib
import json
import platform
import sqlite3
import subprocess
from pathlib import Path
from app.permanent import parse_document
from app.journal import expand_history


def audit():
    folder = Path('docs/manual/evidence/alpha-captions')
    checks = []
    def read(name):
        return json.loads((folder / name).read_text(encoding='utf-8'))
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    report = read('report.json')
    check('Actual caption UI run', report.get('ok') and not report.get('errors'))
    first, second = read('permanent.json'), read('reexport.json')
    state = parse_document(first)
    check('JSON v2 unchanged', first['version'] == second['version'] == 2)
    check('Exact state/IDs after import', state == parse_document(second))
    check('Complete source history archived', any(a['history'] == first['history'] for a in second['importedHistory']))
    check('Journal reaches exact graph', list(expand_history(first))[-1]['state'] == state)
    check('No derived node labels', all(n['label'] == '' for n in state['nodes']))
    ids = report['ids']
    check('Anonymous alphas have no dictionary writes', not any(d['target'] in {ids['inner'], ids['outer'], ids['twin']} for d in state['designations']))
    check('Same-looking structures retain different IDs', ids['inner'] != ids['twin'] and {e['to'] for e in state['edges'] if e['from'] == ids['inner']} == {e['to'] for e in state['edges'] if e['from'] == ids['twin']})
    check('Nested alpha still references ID', any(e['from'] == ids['outer'] and e['to'] == ids['inner'] and e['role'] == 'component' for e in state['edges']))
    check('Chrome performance probes pass', [(p['nodes'], p['edges']) for p in report['performance']] == [(80, 160), (1000, 3000)] and all(p['ms'] < 2000 for p in report['performance']))
    for name in ['alpha', 'builder', 'designations', 'permanent']:
        result = read('regression-' + name + '.json')
        check('GUI regression: ' + name, result.get('ok') and not result.get('errors') and not result.get('failure'))
    for name in ['app/permanent.py', 'app/alpha.py', 'app/builder.py', 'app/store.py', 'app/journal.py', 'app/designations.py', 'data/dictionary/lemmas.json']:
        original = subprocess.check_output(['git', 'show', '40e0a8e:' + name])
        current = Path(name).read_bytes().replace(b'\r\n', b'\n')
        check('Unchanged model/storage: ' + name, original == current)
    files = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'verification.json']
    result = {'result': 'passed', 'base': '40e0a8e', 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'checks': checks, 'files': files}
    (folder / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f'{len(checks)} caption evidence checks passed')


if __name__ == '__main__':
    audit()
