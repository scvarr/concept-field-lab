"""K001: ручные предложения структуры через неизменённые операции редактора.

Это воспроизводимая запись решения Codex, а не извлечение знаний или
проверка семантики LLM. Повторная генерация получает новые UUID; для
продолжения с прежними ID импортировать сохранённый JSON, не генерировать.
"""
import argparse
import json
from pathlib import Path

from app.exchange import graph_export
from app.store import Store, validate

SOURCE = "K001; ручная гипотеза Codex, 11.10.2026; docs/discussion/conclusion.md, раздел 12"
BASE = "масса объём форма размер поверхность материал структура твёрдость хрупкость прочность плотность пористость температура влажность цвет блеск".split()
EXTRA = "длина ширина высота площадь кривизна симметрия граница рельеф шероховатость смачиваемость состав зернистость слоистость трещина вещество упругость растворимость прозрачность теплопроводность теплоёмкость электропроводность магнитность текстура состояние край грань вершина угол происхождение".split()
QUANTITIES = set("масса объём плотность температура длина площадь кривизна угол".split())
PROPERTIES = set("форма размер твёрдость хрупкость прочность пористость влажность цвет блеск симметрия рельеф шероховатость смачиваемость зернистость слоистость упругость растворимость прозрачность теплопроводность теплоёмкость электропроводность магнитность текстура происхождение".split())
EXPANSIONS = {
    "тело": "масса объём форма размер поверхность материал структура состояние",
    "размер": "длина ширина высота объём",
    "форма": "граница кривизна симметрия",
    "граница": "край грань вершина",
    "край": "длина кривизна",
    "грань": "площадь форма",
    "вершина": "угол",
    "поверхность": "площадь рельеф шероховатость цвет блеск смачиваемость текстура прозрачность",
    "структура": "состав зернистость пористость слоистость трещина",
    "материал": "вещество состав плотность твёрдость прочность хрупкость упругость растворимость теплопроводность теплоёмкость электропроводность магнитность прозрачность",
    "состояние": "температура влажность",
    "трещина": "форма размер поверхность",
    "рельеф": "форма размер",
    "зернистость": "размер форма",
    "текстура": "цвет рельеф",
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def act(store, action, **data):
    return store.mutate(action, data, store.read()["revision"])["result"]


def current(store):
    studies = store.read()["state"]["studies"]
    if len(studies) != 1:
        raise ValueError("Ожидалось одно исследование в собственной базе K001")
    return studies[0]


def add_node(store, sid, label):
    return act(store, "add_node", studyId=sid, label=label, kind="", source=SOURCE)["nodeId"]


def connect(store, sid, ids, a, b, relation):
    act(store, "add_edge", studyId=sid, **{
        "from": ids[a], "to": ids[b], "type": relation, "role": "relation", "notes": ""})


def baseline(store):
    if store.read()["state"]["studies"]:
        raise ValueError("Исходный вариант создаётся только в пустой собственной базе")
    result = act(store, "create_study", title="Камень — K001", label="камень",
                 description="Ручная гипотеза описания отдельного физического камня. Аспекты не назначают значения; разновидность не запускает наследование. Не определение и не подтверждённые знания. Легенда: docs/discussion/conclusion.md §12.")
    sid, root = result["studyId"], result["nodeId"]
    act(store, "edit_node", studyId=sid, nodeId=root, label="камень", kind="", source=SOURCE,
        notes="", alternatives="Рабочее чтение: отдельное физическое тело. Материал, драгоценность и другие значения не отождествлены.")
    ids = {"камень": root}
    for label in ["тело", "характеристика", "величина"] + BASE:
        ids[label] = add_node(store, sid, label)
    connect(store, sid, ids, "камень", "тело", "разновидность")
    for label in BASE:
        connect(store, sid, ids, "камень", label, "аспект")
    connect(store, sid, ids, "величина", "характеристика", "разновидность")
    for label in BASE:
        if label in QUANTITIES | PROPERTIES:
            connect(store, sid, ids, label, "величина" if label in QUANTITIES else "характеристика", "разновидность")


def expand(store):
    study = current(store)
    sid = study["id"]
    ids = {n["label"]: n["id"] for n in study["nodes"]}
    if any(label in ids for label in EXTRA):
        raise ValueError("Пересмотр уже выполнен; не повторять его без изменений")
    for label in EXTRA:
        ids[label] = add_node(store, sid, label)
    connect(store, sid, ids, "камень", "состояние", "аспект")
    connect(store, sid, ids, "камень", "происхождение", "аспект")
    for label in EXTRA:
        if label in QUANTITIES | PROPERTIES:
            connect(store, sid, ids, label, "величина" if label in QUANTITIES else "характеристика", "разновидность")
    for label in ("ширина", "высота"):
        connect(store, sid, ids, label, "длина", "разновидность")
    for a, targets in EXPANSIONS.items():
        for b in targets.split():
            connect(store, sid, ids, a, b, "аспект")


def export(store, path):
    validate(store.read()["state"])
    study = current(store)
    write(path, graph_export(store, study["id"]))
    print(json.dumps({"path": str(path), "revision": store.read()["revision"],
                      "nodes": len(study["nodes"]), "edges": len(study["edges"])}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "expand", "export"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.db)
    if args.phase == "baseline":
        baseline(store)
    elif args.phase == "expand":
        expand(store)
    export(store, args.output)


if __name__ == "__main__":
    main()
