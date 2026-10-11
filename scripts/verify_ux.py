"""Validate M004 observations and downloaded exports, without controlling a browser."""
import argparse
import hashlib
import json
import platform
import sqlite3
from pathlib import Path
from app.store import Store, validate
from app.exchange import parse_document


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',default='local-data/ux-m004/run2.sqlite3');parser.add_argument('--downloads',default=str(Path.home()/'Downloads'));parser.add_argument('--output',default='docs/manual/evidence/ux/verification.json');args=parser.parse_args()
    results=[]
    def check(name,condition):
        results.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    stone=Path('data/experiments/stone/stone.json')
    sha=hashlib.sha256(stone.read_bytes()).hexdigest();check('canonical K001 unchanged',sha=='78a4ad3ffcd03ff0cb475e9f542f1d3d1f6aa20630c6a36ee9c4656c9824d4f0')
    snapshot=Store(Path(args.db)).read();validate(snapshot['state']);check('workspace valid',True)
    studies={s['id']:s for s in snapshot['state']['studies']}
    check('independent originals survive explicit merge',len(studies['3876eb26-b999-4868-a889-7f7ed2617ee4']['nodes'])==29 and len(studies['ux-process']['nodes'])==8)
    check('large fixture complete in data',len(studies['ux-large']['nodes'])==1200 and len(studies['ux-large']['edges'])==1799)
    merged=next(s for s in studies.values() if s['title']=='UX — проверочное объединение')
    check('merge preserves origins of both selected candidates',any(len(n['origins'])==2 and {o['studyId'] for o in n['origins']}=={'3876eb26-b999-4868-a889-7f7ed2617ee4','ux-process'} for n in merged['nodes']))
    evidence=Path('docs/manual/evidence/ux');drag=json.loads((evidence/'all-edges-drag.json').read_text(encoding='utf-8'));before={e['id']:e for e in drag['before']['edges']};active=[s for s in drag['samples'] if s['active'] and s['node']!='translate(240,0)']
    check('multiple live drag positions before release',len({s['node'] for s in active})>=4)
    check('camera fixed throughout drag',all(s['camera']==drag['before']['camera'] for s in drag['samples']))
    check('no save during drag',all('Сохранено' in s['status'] for s in active))
    incident={k for k,e in before.items() if 'ux-importcheck-n1' in (e['from'],e['to'])}
    check('all incident paths including loop move in every live sample',all({e['id'] for e in s['edges'] if e['path']!=before[e['id']]['path']}==incident for s in active))
    check('incident labels move simultaneously',all(all((e['labelX'],e['labelY'])!=(before[e['id']]['labelX'],before[e['id']]['labelY']) for e in s['edges'] if e['id'] in incident) for s in active))
    check('unrelated paths and labels stable',all(all(all(e[k]==before[e['id']][k] for k in ('path','labelX','labelY')) for e in s['edges'] if e['id'] not in incident) for s in active))
    large=json.loads((evidence/'large-drag-samples.json').read_text(encoding='utf-8'))['samples'];check('large drag updates live and preserves camera',len({s['node'] for s in large if s['active']})>=4 and len({s['camera'] for s in large})==1)
    final=json.loads((evidence/'final-drag-samples.json').read_text(encoding='utf-8'));live=[s for s in final['samples'] if s['active']]
    check('final renderer has multiple intermediate positions',len({s['node'] for s in live})>=4)
    check('visible and hit paths agree during drag',all(s['edge']==s['hit'] for s in live))
    check('final camera stays fixed before release',all(s['camera']==final['before']['camera'] for s in live))
    browser=json.loads((evidence/'browser-report.json').read_text(encoding='utf-8'));scenarios={s['id']:s for s in browser['scenarios']}
    returned=scenarios[2]['immediateReturn'];check('immediate return while saving restores camera',returned['before']==returned['after'] and returned['before']!=returned['root'] and returned['status']=='Сохранение…')
    reload=scenarios[3]['camera'];check('reload restores camera and manual position',reload['before']==reload['after'] and reload['positionBefore']==reload['positionAfter'])
    pair=scenarios[5];check('comparison pan is independent with shared scale',pair['pairBefore'][0]['camera']!=pair['pairAfter'][0]['camera'] and pair['pairBefore'][1]['camera']==pair['pairAfter'][1]['camera'] and len({json.loads(p['camera'])['scale'] for p in pair['pairAfter']})==1)
    narrow=browser['narrow'];check('narrow inspector stays inside viewport',narrow['inspectorBottom']<=narrow['viewport'][1] and narrow['bodyWidth']==narrow['viewport'][0])
    history=Store(Path(args.db)).history();check('restore appends and retains later history',any(r['action']=='restore' for r in history) and any(r['id']==18 for r in history))
    exports=[]
    for filename,kind in [('concept-field-diff.json','diff'),('concept-field-workspace.json','workspace'),('concept-field-graph.json','study'),('concept-field-graph (1).json','fragment')]:
        p=Path(args.downloads)/filename;data=json.loads(p.read_text(encoding='utf-8'));check(f'browser downloaded {kind} v2',data.get('kind')==kind and data.get('version')==2)
        if kind!='diff':parse_document(data)
        exports.append({'file':filename,'kind':kind,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    output={'result':'passed','checks':results,'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'revision':snapshot['revision'],'stoneSha256':sha,'activeDragSamples':len(active),'incidentEdges':len(incident),'unchangedEdges':len(before)-len(incident),'downloads':exports}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True);Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print(f'{len(results)} UX evidence/export checks passed')


if __name__=='__main__':main()
