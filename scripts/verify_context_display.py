"""Independent finite checks of M012 saved SVG geometry and ID roundtrip."""
import argparse
import hashlib
import json
import math
import platform
import sqlite3
import subprocess
from pathlib import Path
from app.permanent import parse_document
from app.journal import expand_history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', default='docs/manual/evidence/context-display')
    folder = Path(parser.parse_args().evidence)
    load = lambda name: json.loads((folder/name).read_text(encoding='utf-8'))
    checks = []
    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    report, doc, again = load('report.json'), load('permanent.json'), load('reexport.json')
    state = parse_document(doc)
    check('Eight browser groups and no page/UI error toasts', report['ok'] and len(report['checks']) == 8 and not report['errors'])
    check('Exact import state and complete archived history', parse_document(again) == state and any(d['history'] == doc['history'] for d in again['importedHistory']))
    check('Canonical five nodes/four edges/three contexts', [len(state[k]) for k in ['nodes', 'edges', 'contextEdges']] == [5, 4, 3])
    edges = {e['id']: e for e in state['edges']}
    ids = report['ids']['edges']
    check('Explicit reversal and no unconfirmed cross-branch pair', {(c['from'], c['to']) for c in state['contextEdges']} == {(ids[1], ids[0]), (ids[0], ids[2]), (ids[1], ids[2])})
    check('Only identity/provenance stored for context, not SVG geometry', all(set(c) == {'id', 'from', 'to', 'definitionId'} for c in state['contextEdges']))
    check('Valid full journal ends in exported state', list(expand_history(doc))[-1]['state'] == state)
    for number, sample in enumerate(report['geometry']):
        positions = {n['id']: n for n in sample['nodes']}
        valid = sample['shown'] == len(sample['links']) and sample['blocked'] == 0
        for c in sample['links']:
            valid &= c['from'] in edges and c['to'] in edges and c['dash'] != 'none' and 'context-arrow' in c['marker']
            points = c['points']
            for a, b in zip(points, points[1:]):
                valid &= a['x'] == b['x'] or a['y'] == b['y']
                for n in positions.values():
                    if a['x'] == b['x']:
                        valid &= not (n['x']-80 < a['x'] < n['x']+80 and max(a['y'], b['y']) > n['y']-28 and min(a['y'], b['y']) < n['y']+28)
                    else:
                        valid &= not (n['y']-28 < a['y'] < n['y']+28 and max(a['x'], b['x']) > n['x']-80 and min(a['x'], b['x']) < n['x']+80)
            # This fixture's ordinary pairs are distinct straight relations.
            # Check attachment independently by distance/projection onto those lines.
            for p, edge_id in [(points[0], c['from']), (points[-1], c['to'])]:
                edge = edges[edge_id]
                a, b = positions[edge['from']], positions[edge['to']]
                dx, dy = b['x']-a['x'], b['y']-a['y']
                length = math.hypot(dx, dy)
                valid &= abs((p['x']-a['x'])*dy-(p['y']-a['y'])*dx)/length < 1e-7
                projection = ((p['x']-a['x'])*dx+(p['y']-a['y'])*dy)/length**2
                valid &= 0 < projection < 1
        check('Saved SVG sample '+str(number)+' attaches to edge IDs, is orthogonal and avoids all nodes', valid)
    check('Covered ports explicitly counted, not replaced by intersecting lines', report['blocked']['blocked'] > 0 and report['blocked']['shown']+report['blocked']['blocked'] == 3)
    p = report['performance']
    check('Maximum draft probe accounted for all 800 contexts within finite time', p['shown']+p['blocked'] == 800 and p['limited'] == 0 and p['firstMs'] < 5000 and p['redrawMs'] < 5000)
    for name in ['regression-canvas.json', 'regression-legacy.json']:
        r = load(name)
        check('Regression '+name, r['ok'] and not r['errors'])
    for name in ['app/builder.py', 'app/permanent.py', 'app/store.py', 'app/designations.py', 'app/dictionary.py', 'app/definitions.py', 'app/server.py', 'data/dictionary/lemmas.json', 'data/experiments/stone/stone.json', 'data/experiments/transfer/transfer.json', 'data/experiments/nut/nut-revised.json']:
        check('Unchanged Git object '+name, subprocess.check_output(['git', 'hash-object', name]).strip() == subprocess.check_output(['git', 'rev-parse', '048c8ca:'+name]).strip())
    output = {'result': 'passed', 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'baseCheckpoint': '048c8ca1ce400371f7d1d091bd408003e6d33a6f', 'checks': checks,
              'files': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'verification.json']}
    (folder/'verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(f'{len(checks)} independent M012 checks passed')


if __name__ == '__main__':
    main()
