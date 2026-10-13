"""Finite M009 evidence checks, independent of browser interactions."""
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
    parser.add_argument('--evidence', default='docs/manual/evidence/designations')
    args = parser.parse_args()
    directory = Path(args.evidence)
    read = lambda name: json.loads((directory / name).read_text(encoding='utf-8'))
    checks = []
    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    report = read('report.json')
    document = read('permanent.json')
    state = parse_document(document)
    reexport = read('reexport.json')
    check('UI scenario and page errors', report['ok'] and len(report['scenarios']) == 7 and not report['errors'])
    check('Exact roundtrip and original history archived', parse_document(reexport) == state and any(d['history'] == document['history'] for d in reexport['importedHistory']))
    ids = report['ids']
    check('Canonical ordinary/context IDs', [e['id'] for e in state['edges']] == ids['ordinaryEdges'] and [c['id'] for c in state['contextEdges']] == ids['contexts'])
    check('Four concepts, six external designations and two publications', len(state['nodes']) == 4 and len(state['designations']) == 6 and len(state['definitionPublications']) == 2)
    results = search(state, 'гайка')
    check('One word returns two distinct ID entry points with neighbourhood', {c['nodeId'] for c in results['concepts']} == {ids['detail'],ids['bird']} and all(c['edges'] and c['origins'] and c['designations'] for c in results['concepts']))
    senses = {(d['target'],d['lexicalSource']['senseId']) for d in state['designations'] if d['text'] == 'гайка'}
    check('Distinct optional sense provenance and revision', senses == {(ids['detail'],'1'),(ids['bird'],'5')} and all(str(d['lexicalSource']['revision']) == '14297625' for d in state['designations'] if d['text'] == 'гайка'))
    pairs = {(c['from'],c['to']) for c in state['contextEdges']}
    check('Directed context limited to the two selected routes', pairs == {(ids['ordinaryEdges'][0],ids['ordinaryEdges'][1]),(ids['ordinaryEdges'][2],ids['ordinaryEdges'][3])})
    rows = list(expand_history(document))
    changes = 0
    for previous, row in zip(rows, rows[1:]):
        if row['action'] in ('designation_save','designation_remove'):
            changes += 1
            check(f'Alias action at revision {row["id"]} leaves structure and draft history unchanged', all(previous['state'][k] == row['state'][k] for k in ('nodes','edges','contextEdges','definitionDrafts','definitionPublications')))
    check('Actual separate alias mutations present', changes >= 5)
    retained = ['data/experiments/stone/stone.json','data/experiments/transfer/transfer.json','data/experiments/nut/nut-revised.json','docs/manual/evidence/builder/verified-workspace.json','data/dictionary/lemmas.json']
    for name in retained:
        actual = subprocess.check_output(['git','hash-object',name],text=True).strip()
        original = subprocess.check_output(['git','rev-parse','3cd2dcd:'+name],text=True).strip()
        check('Unchanged historical Git object: '+name, actual == original)
    output = {'result':'passed','checks':checks,'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,
              'sourceCheckpoint':'950768628baa5fa0fc47b15f34999fc34e90a7f8',
              'files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in sorted(directory.iterdir()) if p.is_file() and p.name != 'verification.json']}
    (directory/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(f'{len(checks)} M009 evidence checks passed')


if __name__ == '__main__':
    main()
