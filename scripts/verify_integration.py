"""Read-only integration audit of Git ancestry, retained data and saved GUI runs."""
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
from pathlib import Path


def git(*args):
    return subprocess.check_output(['git', *args]).decode('utf-8').strip()


def audit(folder, base, candidate):
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    base, candidate = git('rev-parse', base), git('rev-parse', candidate)
    check('Fast-forward ancestry', git('merge-base', base, candidate) == base)
    retained = git('ls-tree', '-r', '--name-only', base, '--', 'archive', 'data/experiments', 'data/fixtures', 'docs/research').splitlines()
    for name in retained:
        check('Historical Git blob: ' + name, git('rev-parse', base + ':' + name) == git('rev-parse', candidate + ':' + name))
    for name in git('ls-tree', '-r', '--name-only', base, '--', 'docs/discussion').splitlines():
        if name != 'docs/discussion/active-context.md':
            check('Historical discussion: ' + name, git('rev-parse', base + ':' + name) == git('rev-parse', candidate + ':' + name))
    # Layout, journal and scientific mechanism are outside M007–M012 changes.
    for name in ['app/composition.py', 'app/journal.py', 'app/geometry.py', 'app/static/layout-engine.js', 'app/static/layout-controls.js', 'app/static/layout-worker.js']:
        check('Retained engine: ' + name, git('rev-parse', base + ':' + name) == git('rev-parse', candidate + ':' + name))
    for name in ['app/builder.py', 'app/permanent.py', 'app/store.py', 'app/designations.py', 'app/dictionary.py', 'app/definitions.py', 'data/dictionary/lemmas.json']:
        check('M010–M012 retain M009 core: ' + name, git('rev-parse', '02a3a1f:' + name) == git('rev-parse', candidate + ':' + name))
    runs = {}
    for name in ['context', 'canvas', 'designations', 'permanent', 'workspace-views', 'builder', 'composition', 'layout', 'browser']:
        report = json.loads((folder / name / 'report.json').read_text(encoding='utf-8'))
        success = report.get('ok') or report.get('success') or report.get('result') == 'passed'
        check('GUI run: ' + name, success and not report.get('failure') and not report.get('errors') and not report.get('pageErrors'))
        runs[name] = {'groups': len(report.get('checks', report.get('scenarios', []))), 'browser': report.get('browser'), 'counts': report.get('counts'), 'date': report.get('date')}
    from app.permanent import parse_document
    from app.journal import expand_history
    for name in ['context', 'canvas', 'designations', 'permanent']:
        document = json.loads((folder / name / 'permanent.json').read_text(encoding='utf-8'))
        again = json.loads((folder / name / 'reexport.json').read_text(encoding='utf-8'))
        check('Exact state/full imported history: ' + name, parse_document(document) == parse_document(again) and any(a['history'] == document['history'] for a in again['importedHistory']))
        check('Full journal ends in state: ' + name, list(expand_history(document))[-1]['state'] == document['state'])
    files = [{'name': p.relative_to(folder).as_posix(), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.rglob('*')) if p.is_file() and p != folder / 'verification.json']
    result = {'result': 'passed', 'base': base, 'candidate': candidate, 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'historicalFiles': len(retained), 'checks': checks, 'runs': runs, 'files': files}
    (folder / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(f'{len(checks)} integration checks passed; {len(retained)} historical Git blobs retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, default=Path('docs/manual/evidence/integration'))
    parser.add_argument('--base', default='origin/main')
    parser.add_argument('--candidate', default='HEAD')
    args = parser.parse_args()
    audit(args.evidence, args.base, args.candidate)
