"""M005: isolated browser inputs, not semantic judgments about K001/K002."""
import argparse
import json
from pathlib import Path

from app.store import Store, uid

ROOT = Path(__file__).resolve().parents[1]


def act(store, action, **data):
    return store.mutate(action, data, store.read()["revision"])["result"]


def accept(store, document):
    act(store,"import",document=document)
    ids=[p["id"] for p in store.read()["state"]["proposals"] if p["status"]=="pending"]
    if ids:act(store,"review_proposals",decision="accept",proposalIds=ids)


def synthetic(store,title):
    made=act(store,"create_study",title=title,label="корень "+title,
             description="Синтетическая инженерная структура; решения проверяют редактор, не смысл.")
    sid=made["studyId"]
    shared=act(store,"add_node",studyId=sid,label="общий",notes="Только синтетическая проверка ручного решения")["nodeId"]
    refused=act(store,"add_node",studyId=sid,label="спорный")["nodeId"]
    terminal=act(store,"add_node",studyId=sid,label="конец "+title)["nodeId"]
    for nid,text in ((shared,"словарное совпадение"),(refused,"сохранённый отказ")):
        act(store,"add_designation",studyId=sid,target=nid,text=text,notes="Синтетический словарь")
    if title=="Источник A":
        act(store,"add_designation",studyId=sid,target=made["nodeId"],text="удалённые узлы",notes="Для проверки большого индекса")
        act(store,"add_designation",studyId=sid,target=made["nodeId"],text="массовое совпадение",notes="Для проверки большого индекса")
    for a,b,kind in ((made["nodeId"],shared,"первичное"),(shared,refused,"параллельное"),(shared,terminal,"конечное")):
        act(store,"add_edge",studyId=sid,**{"from":a,"to":b,"type":kind,"notes":"Синтетическая связь "+title})
    return {"studyId":sid,"rootId":made["nodeId"],"shared":shared,"refused":refused,"terminal":terminal}


def large(store,count):
    made=act(store,"create_study",title="Большой источник",label="Большой корень",description="Только инженерная проверка индекса / инспекторов / пределов")
    sid,root=made["studyId"],made["nodeId"]
    ids=[root]+[uid() for _ in range(count-1)]
    changes=[]
    for i,nid in enumerate(ids):
        if i:
            value={"id":nid,"label":f"Большой узел {i}","kind":"","notes":"Синтетический элемент","alternatives":"","source":"M005 fixture","origins":[],"x":(i%35)*260,"y":(i//35)*90}
            if i==count-1:value.update(label="Сильно удалённый узел",x=50000,y=0)
            changes.append({"operation":"node","studyId":sid,"base":None,"value":value})
        if i in (0,count-1) or 1<=i<=200:
            changes.append({"operation":"designation","studyId":sid,"base":None,"value":{"id":uid(),"text":"удалённые узлы" if i in (0,count-1) else "массовое совпадение","target":nid,"notes":"Синтетическая инженерная группа","source":"M005 fixture","origins":[]}})
    pairs=[]
    for i in range(1,count):pairs.append((0,i) if i<=count//2 else (i-1,i))
    for i in range(1,count//2):pairs.append((i,i+1))
    for i,(a,b) in enumerate(pairs):
        changes.append({"operation":"edge","studyId":sid,"base":None,"value":{"id":uid(),"from":ids[a],"to":ids[b],"type":"большое раскрытие","notes":f"Техническое ребро {i}","origins":[]}})
    accept(store,{"format":"concept-field-graph","version":3,"kind":"changes","changes":changes})
    return {"studyId":sid,"rootId":root,"farId":ids[-1],"nodes":count,"edges":len(pairs)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--large",type=int,default=2000)
    args=parser.parse_args()
    if not args.db.resolve().is_relative_to(ROOT/"local-data/accumulation-m005"):
        parser.error("Только собственный каталог local-data/accumulation-m005")
    if not 300<=args.large<=3000:parser.error("Проверочный размер от 300 до 3000")
    store=Store(args.db)
    if store.read()["state"]["studies"]:parser.error("Нужна пустая собственная база; прежние данные не удаляются")
    actual={}
    for name,file in (("K001","data/experiments/stone/stone.json"),("K002","data/experiments/transfer/transfer.json")):
        doc=json.loads((ROOT/file).read_text(encoding="utf-8"));accept(store,doc);actual[name]=doc["state"]["studies"][0]["id"]
    inputs={name:synthetic(store,"Источник "+name) for name in ("A","B","C")}
    inputs["large"]=large(store,args.large)
    inputs["actual"]=actual
    inputs["db"]=str(args.db);inputs["revision"]=store.read()["revision"]
    path=args.db.parent/(args.db.stem+"-manifest.json")
    path.write_text(json.dumps(inputs,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"manifest":str(path),"revision":inputs["revision"],"large":inputs["large"]},ensure_ascii=False))


if __name__=="__main__":main()
