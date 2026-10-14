"""Reproduce finite M011 evidence checks without operating the browser."""
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
from pathlib import Path
from app.permanent import parse_document
from app.journal import expand_history
from app.dictionary import search


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', default='docs/manual/evidence/canvas')
    folder = Path(parser.parse_args().evidence)
    load = lambda name: json.loads((folder/name).read_text(encoding='utf-8'))
    checks = []
    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    report, doc, reexport = load('report.json'), load('permanent.json'), load('reexport.json')
    state, ids = parse_document(doc), report['ids']
    check('Seven full canvas groups, zero page errors', report['ok'] and len(report['checks']) == 7 and not report['errors'])
    check('No document overflow in five viewport sizes', len(report['sizes']) == 5 and all(r['scrollWidth'] == r['width'] and r['scrollHeight'] == r['height'] and r['canvas']['bottom'] <= r['height'] for r in report['sizes']))
    check('Exact export/import/reexport state and preserved incoming history', parse_document(reexport) == state and any(a['history'] == doc['history'] for a in reexport['importedHistory']))
    check('Canonical counts and reused original edge IDs', len(state['nodes']) == 4 and len(state['edges']) == 4 and len(state['contextEdges']) == 3 and len(state['designations']) == 6 and [e['id'] for e in state['edges']] == ids['ordinaryEdges'])
    words = search(state, 'гайка')
    check('Two distinct entry IDs with lexical sources and neighbourhood', {c['nodeId'] for c in words['concepts']} == {ids['detail'], ids['bird']} and all(c['edges'] and c['designations'] for c in words['concepts']))
    check('Distinct sense 1/5 links keep revision 14297625', {(d['target'], d['lexicalSource']['senseId'], str(d['lexicalSource']['revision'])) for d in state['designations'] if d['text'] == 'гайка'} == {(ids['detail'], '1', '14297625'), (ids['bird'], '5', '14297625')})
    e = ids['ordinaryEdges']
    check('Only confirmed pairs, with the explicit manual reversal', {(c['from'], c['to']) for c in state['contextEdges']} == {(e[1], e[0]), (e[0], e[2]), (e[1], e[2])})
    rows = list(expand_history(doc))
    mutations = 0
    for old, new in zip(rows, rows[1:]):
        if new['action'] in ('designation_save', 'designation_remove'):
            mutations += 1
            check('Independent correspondence operation at revision '+str(new['id']), all(old['state'][k] == new['state'][k] for k in ['nodes', 'edges', 'contextEdges', 'definitionDrafts', 'definitionPublications']))
    check('Actual canonical alias edit in history', mutations > 0)
    for name in ['regression-designations.json', 'regression-permanent.json', 'regression-views.json', 'regression-legacy.json']:
        r = load(name)
        check('Regression '+name, r['ok'] and not r['errors'])
    for name in ['app/builder.py', 'app/permanent.py', 'app/store.py', 'app/designations.py', 'app/dictionary.py', 'app/definitions.py', 'data/dictionary/lemmas.json', 'data/experiments/stone/stone.json', 'data/experiments/transfer/transfer.json', 'data/experiments/nut/nut-revised.json', 'docs/manual/evidence/builder/verified-workspace.json']:
        check('Unchanged Git object '+name, subprocess.check_output(['git', 'hash-object', name]).strip() == subprocess.check_output(['git', 'rev-parse', '4473a6f:'+name]).strip())
    output = {'result': 'passed', 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
              'sourceCheckpoint': '1f31d428fcae9dcfb6539b5a260519535e4e38b5', 'checks': checks,
              'files': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'verification.json']}
    (folder/'verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(f'{len(checks)} independent M011 evidence checks passed')


if __name__ == '__main__':
    main()
