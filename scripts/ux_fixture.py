"""M004 disposable independent fixtures; never writes the research graph."""
import argparse
import hashlib
import json
from pathlib import Path
from app.store import Store
from app.exchange import graph_export


def fixture(name, count):
    sid = 'ux-' + name
    nodes = [dict(id=f'{sid}-n{i}', label=('процесс' if i == 0 else 'материал' if i == 1 else 'p-shape' if i == 2 else f'элемент {i}'),
                  kind='', notes='Синтетическая UX-фикстура', alternatives='', source='scripts/ux_fixture.py', origins=[],
                  x=(i % 12) * 240, y=(i // 12) * 90) for i in range(count)]
    edges = [dict(id=f'{sid}-e{i}', **{'from':nodes[(i-1)//3]['id'], 'to':nodes[i]['id']}, type='аспект', role='relation', notes='', origins=[]) for i in range(1, count)]
    edges += [dict(id=f'{sid}-cross{i}', **{'from':nodes[i]['id'], 'to':nodes[i+1]['id']}, type='связь', role='relation', notes='', origins=[]) for i in range(1,count-1,2)]
    edges.append(dict(id=f'{sid}-self', **{'from':nodes[1]['id'],'to':nodes[1]['id']},type='петля',role='relation',notes='',origins=[]))
    study=dict(id=sid,title='Процесс — UX' if name=='process' else 'Большой граф — UX',description='Независимая синтетическая проверка интерфейса, не знания',rootId=nodes[0]['id'],archived=False,nodes=nodes,edges=edges,designations=[dict(id=f'{sid}-d1',text='форма',target=nodes[2]['id'],notes='Обозначение отличается от технического имени',source='UX fixture',origins=[])],substitutions=[])
    return {'format':'concept-field-graph','version':2,'kind':'study','state':{'studies':[study],'matches':[],'imports':[],'proposals':[]}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',default='local-data/ux-m004/workspace.sqlite3');args=parser.parse_args()
    db=Path(args.db);store=Store(db)
    if store.read()['state']['studies']:raise SystemExit('Fixture setup requires an empty disposable database')
    out=db.parent;out.mkdir(parents=True,exist_ok=True)
    stone=Path('data/experiments/stone/stone.json')
    for name,doc in [('stone',json.loads(stone.read_text(encoding='utf-8'))),('process',fixture('process',8)),('large',fixture('large',1200))]:
        result=store.mutate('import',{'document':doc},store.read()['revision'])
        pending=[p['id'] for p in result['state']['proposals'] if p['status']=='pending']
        store.mutate('review_proposals',{'proposalIds':pending,'decision':'accept','reason':'Изолированный UX-тест'},store.read()['revision'])
        (out/f'{name}.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    manifest={'stoneSha256':hashlib.sha256(stone.read_bytes()).hexdigest(),'studies':[{'id':s['id'],'nodes':len(s['nodes']),'edges':len(s['edges'])} for s in store.read()['state']['studies']]}
    (out/'fixtures.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=='__main__':main()
