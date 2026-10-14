"""Независимый конечный аудит M017: сохранённые SVG, ID, JSON и Git blobs."""
import hashlib
import json
import math
import platform
import re
import sqlite3
import subprocess
from pathlib import Path
from app.permanent import parse_document
from app.journal import expand_history


def audit():
    folder = Path('docs/manual/evidence/context-markers')
    read = lambda name: json.loads((folder / name).read_text(encoding='utf-8'))
    checks = []

    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    def segment_clear(a, b, n):
        if n.get('radius'):
            dx, dy = b['x']-a['x'], b['y']-a['y']
            t = max(0, min(1, ((n['x']-a['x'])*dx+(n['y']-a['y'])*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
            return math.hypot(a['x']+t*dx-n['x'], a['y']+t*dy-n['y']) >= n['radius']-1e-7
        lo, hi = 0, 1
        for origin, delta, lower, upper in [(a['x'], b['x']-a['x'], n['x']-80, n['x']+80), (a['y'], b['y']-a['y'], n['y']-28, n['y']+28)]:
            if abs(delta) < 1e-12:
                if origin <= lower or origin >= upper:
                    return True
            else:
                t, u = (lower-origin)/delta, (upper-origin)/delta
                lo, hi = max(lo, min(t, u)), min(hi, max(t, u))
        return lo >= hi-1e-10

    def curves_clear(links, nodes):
        for c in links:
            for controls in c['segments']:
                for n in nodes:
                    if len(controls) == 2:
                        if not segment_clear(*controls, n):
                            return False
                    else:
                        # Entire Bezier lies in the control hull, hence inside its box.
                        radius = n.get('radius')
                        left, right = n['x']-(radius or 80), n['x']+(radius or 80)
                        top, bottom = n['y']-(radius or 28), n['y']+(radius or 28)
                        if min(p['x'] for p in controls) < right and max(p['x'] for p in controls) > left and min(p['y'] for p in controls) < bottom and max(p['y'] for p in controls) > top:
                            return False
        return True

    def svg_segments(d):
        tokens = re.findall(r'[MLQ]|[-+]?(?:\d*\.)?\d+(?:e[-+]?\d+)?', d, re.I)
        point, segments = None, []
        i = 0
        while i < len(tokens):
            command = tokens[i]
            count = 4 if command == 'Q' else 2
            values = [float(v) for v in tokens[i+1:i+1+count]]
            controls = [{'x': values[j], 'y': values[j+1]} for j in range(0, count, 2)]
            if command != 'M':
                segments.append([point, *controls])
            point = controls[-1]
            i += count+1
        return segments

    report, first, again = read('report.json'), read('permanent.json'), read('reexport.json')
    check('Chrome: все девять групп, без ошибок', report['ok'] and len(report['checks']) == 9 and not report['errors'])
    state = parse_document(first)
    check('JSON v2: точный state после restart/import', first['version'] == again['version'] == 2 and parse_document(again) == state)
    check('Полная архивная история', any(a['history'] == first['history'] for a in again['importedHistory']) and list(expand_history(first))[-1]['state'] == state)
    check('Квадраты/кривые отсутствуют в модели контекста', all(set(c) == {'id', 'from', 'to', 'definitionId'} for c in state['contextEdges']))
    edges = {e['id']: e for e in state['edges']}
    check('Только обычные рёбра участвуют', all(edges[c['from']]['role'] == edges[c['to']]['role'] == 'relation' for c in state['contextEdges']))
    for i, sample in enumerate(report['geometry']):
        markers = {m['id']: m for m in sample['markers']}
        valid = sample['shown'] == len(sample['links']) and not sample['blocked'] and curves_clear(sample['links'], sample['nodes'])
        for c in sample['links']:
            valid &= c['segments'][0][0] == markers[c['from']]['point'] and c['segments'][-1][-1] == markers[c['to']]['point'] and 'context-arrow' in c['marker']
            valid &= svg_segments(c['d']) == c['segments']
        valid &= all(math.hypot(m['point']['x']-m['actual']['x'], m['point']['y']-m['actual']['y']) < .3 for m in markers.values())
        check(f'SVG {i}: фиксированная середина, направление и обход всей кривой', valid)
    check('Закрытые маркеры диагностируются по ID', report['blocked']['blocked'] > 0 and any(d['reason'] == 'marker-covered' for d in report['blocked']['diagnostics']))
    probe = read('probe-report.json')
    check('Прежний M015 JSON и межопределительная пара через GUI', probe['ok'] and not probe['errors'])
    baseline = parse_document(json.loads(Path('docs/manual/evidence/overview/permanent.json').read_text(encoding='utf-8')))
    after = parse_document(read('probe-permanent.json'))
    by_id = lambda values: {v['id']: v for v in values}
    check('Публикация пары сохраняет полные узлы/обычные рёбра', by_id(baseline['nodes']) == by_id(after['nodes']) and by_id(baseline['edges']) == by_id(after['edges']) and len(after['contextEdges']) == len(baseline['contextEdges'])+1)
    for p in probe['probes']:
        if p.get('dense'):
            for name in ['first', 'redraw']:
                result = p[name]
                nodes = p['nodes'] if name == 'first' else [{**n, 'x': 900, 'y': 900} if n['id'] == 'n99' else n for n in p['nodes']]
                check(f'Плотный граф {name}: все 850 учтены, каждый показанный путь безопасен', sum(result[k] for k in ['shown', 'blocked', 'limited']) == 850 and curves_clear(result['paths'], nodes))
            check('Плотный граф: конечное время', p['firstMs'] < 5000 and p['redrawMs'] < 5000)
        else:
            check(f'Петли/параллели/circle={p["circular"]}: стабильные ID и обход', by_id(p['first']) == by_id(p['reordered']) and len(p['first']) == 7 and curves_clear(p['paths'], p['nodes']))
    for name in ['overview', 'canvas', 'provenance']:
        r = read('regression-'+name+'.json')
        check('Регрессия '+name, r['ok'] and not r['errors'])
    for file in sorted(Path('app').glob('*.py')):
        name = file.as_posix()
        check('Прежний backend '+name, subprocess.check_output(['git', 'hash-object', name]).strip() == subprocess.check_output(['git', 'rev-parse', '2fde7df:'+name]).strip())
    output = {'result': 'passed', 'base': '2fde7df', 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'checks': checks,
              'files': [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.iterdir()) if p.is_file() and p.name != 'verification.json']}
    (folder/'verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(f'{len(checks)} независимых проверок M017 прошли')


if __name__ == '__main__':
    audit()
