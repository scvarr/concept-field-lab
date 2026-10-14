"""Independent read-only audit of M015 graph semantics and rendered geometry."""
import copy
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
    folder=Path('docs/manual/evidence/overview')
    read=lambda name: json.loads((folder/name).read_text(encoding='utf-8'))
    checks=[]
    def check(name, condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition: raise AssertionError(name)
    def semantic(state):
        state=copy.deepcopy(state)
        for n in state['nodes']:
            for key in ('x','y','layoutPinned'): n.pop(key,None)
        return state
    report=read('report.json');first=read('permanent.json');second=read('reexport.json');before=read('before.json')
    state=parse_document(first)
    check('Actual M015 browser run',report.get('ok') and not report.get('errors'))
    check('Same JSON v2 and exact roundtrip',first['version']==second['version']==2 and state==parse_document(second))
    check('ID/structure/designations/drafts/context unchanged',semantic(state)==semantic(before))
    check('Full source history archive',any(a['history']==first['history'] for a in second['importedHistory']))
    rows=list(expand_history(first))
    check('Complete history ends in graph',rows[-1]['state']==state)
    check('Explicit layout/pin/undo journal',{'layout_apply','layout_pin','layout_restore'} <= {r['action'] for r in rows})
    check('Pin snapshots survive in history',any(any(n.get('layoutPinned') for n in r['state']['nodes']) for r in rows))
    nodes=report['geometry']['nodes'];indexed={n['id']:n for n in nodes}
    check('Degree and bounded circle radii',all(n['radius']==min(26,8+3*math.sqrt(n['degree'])) for n in nodes))
    check('Two coloured structural types',len({n['colour'] for n in nodes})==2 and {'concept','alpha'}=={n['type'] for n in nodes})
    check('No circle overlaps in preview geometry',all(math.hypot(a['x']-b['x'],a['y']-b['y'])>=a['radius']+b['radius']-1e-6 for i,a in enumerate(nodes) for b in nodes[i+1:]))
    paths={}
    for edge in report['geometry']['edges']:
        values=[float(v) for v in re.findall(r'-?\d+(?:\.\d+)?(?:e[+-]?\d+)?',edge['d'],re.I)]
        a,b=indexed[edge['from']],indexed[edge['to']]
        check('Circle arrow boundaries '+edge['id'],bool(edge['marker']) and abs(math.hypot(values[0]-a['x'],values[1]-a['y'])-a['radius'])<1e-6 and abs(math.hypot(values[-2]-b['x'],values[-1]-b['y'])-b['radius'])<1e-6)
        paths[edge['id']]=values
    contexts={c['id']:c for c in state['contextEdges']}
    fractions=[.5,.35,.65,.2,.8,.1,.9,.05,.95]
    for link in report['geometry']['points']:
        c=contexts[link['id']]
        for endpoint,edge_id in [(link['points'][0],c['from']),(link['points'][-1],c['to'])]:
            v=paths[edge_id]
            check('Context port on actual ordinary curve '+edge_id,any(math.hypot(endpoint['x']-((1-t)**2*v[0]+2*t*(1-t)*v[2]+t*t*v[4]),endpoint['y']-((1-t)**2*v[1]+2*t*(1-t)*v[3]+t*t*v[5]))<1e-6 for t in fractions))
        for a,b in zip(link['points'],link['points'][1:]):
            check('Orthogonal segment '+link['id'],a['x']==b['x'] or a['y']==b['y'])
            for n in nodes:
                distance=math.hypot(a['x']-n['x'],max(min(a['y'],b['y'])-n['y'],0,n['y']-max(a['y'],b['y']))) if a['x']==b['x'] else math.hypot(a['y']-n['y'],max(min(a['x'],b['x'])-n['x'],0,n['x']-max(a['x'],b['x'])))
                check('Context outside circle '+n['id'],distance>=n['radius']-1e-6)
    check('Context shown or explicitly blocked',report['geometry']['shown']+report['geometry']['blocked']==len(state['contextEdges']))
    check('Live worker cancellation is read-only',report.get('workerCancel'))
    check('Zoom hysteresis observed',report['labelModes'].get('hysteresis'))
    check('Whole graph scales include hidden nodes',[(p['size'],p['visible']) for p in report['performance']]==[(100,100),(1000,1000),(2000,2000),(3000,2000)] and all(p['overlaps']==0 and p['elapsedMs']<30000 for p in report['performance']))
    for name in ['alpha','captions','context','canvas','workspace-views','layout']:
        r=read('regression-'+name+'.json');check('GUI regression '+name,(r.get('ok') or r.get('success')) and not r.get('errors') and not r.get('failure'))
    for name in ['app/alpha.py','app/builder.py','app/designations.py','app/journal.py','data/dictionary/lemmas.json']:
        check('Retained semantic engine '+name,subprocess.check_output(['git','show','1d215ab:'+name])==Path(name).read_bytes().replace(b'\r\n',b'\n'))
    files=[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(folder.iterdir()) if p.is_file() and p.name!='verification.json']
    (folder/'verification.json').write_text(json.dumps({'result':'passed','base':'1d215ab','python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'checks':checks,'files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(f'{len(checks)} overview evidence checks passed')


if __name__=='__main__': audit()
