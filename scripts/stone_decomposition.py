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

# Одна выбранная декомпозиция после уточнения пользователя. Путь несёт
# функцию описания камня; это не каталог всех возможных отношений слов.
SELECTED = {
    "камень": "характеристика",
    "характеристика": "масса форма размер поверхность материал структура состояние",
    "форма": "граница кривизна симметрия",
    "размер": "длина объём",
    "поверхность": "площадь шероховатость цвет блеск",
    "материал": "состав плотность твёрдость прочность хрупкость",
    "состав": "вещество",
    "структура": "зернистость пористость слоистость",
    "состояние": "температура влажность",
}
EXCLUSIONS = {
    "тело": "Классификация объекта не раскрывает выбранное описание камня",
    "величина": "Параллельная классификация параметров не нужна выбранной декомпозиции",
    "ширина": "Ориентационная роль длины не задана; не дублировать длину",
    "высота": "Ориентационная роль длины не задана; не дублировать длину",
    "край": "Частный геометрический случай не раскрыт без условий применимости",
    "грань": "Частный геометрический случай не раскрыт без условий применимости",
    "вершина": "Частный геометрический случай не раскрыт без условий применимости",
    "угол": "Относится к исключённому частному геометрическому случаю",
    "рельеф": "Не различён с шероховатостью без масштаба; дополнительные связи не помогают",
    "текстура": "Не различена с цветом/шероховатостью; не обходить это новыми связями",
    "смачиваемость": "Дополнительное направление вне выбранного раскрытия поверхности",
    "трещина": "Наличие части и параметр описания не различены; не имитировать аспектом",
    "упругость": "Каталог дальнейших свойств материала не выполняет функцию в выбранном проходе",
    "растворимость": "Каталог дальнейших свойств материала не выполняет функцию в выбранном проходе",
    "прозрачность": "Не выражено различие материала и наблюдения поверхности; дубли не сохранять",
    "теплопроводность": "Каталог дальнейших свойств материала не выполняет функцию в выбранном проходе",
    "теплоёмкость": "Каталог дальнейших свойств материала не выполняет функцию в выбранном проходе",
    "электропроводность": "Каталог дальнейших свойств материала не выполняет функцию в выбранном проходе",
    "магнитность": "Широкое неоднозначное имя без раскрытия; исключено из выбранного прохода",
    "происхождение": "Только называние вопроса, необходимое различие не представлено",
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


def discard_grouping(store):
    """Удалить только собственную пробу после восстановления прямого ребра."""
    study = current(store)
    combos = [n for n in study["nodes"] if n.get("structure") == "combination"]
    if not combos:
        print("Пробная комбинация уже удалена; повторной мутации нет")
        return
    if len(combos) != 1 or combos[0]["label"]:
        raise ValueError("Ожидалась одна анонимная пробная группировка K001")
    ids = {n["label"]: n["id"] for n in study["nodes"]}
    assert any(e["from"] == ids["камень"] and e["to"] == ids["масса"]
               and e["type"] == "аспект" for e in study["edges"])
    cid = combos[0]["id"]
    affected = [e for e in study["edges"] if cid in (e["from"], e["to"])]
    assert len(affected) == 4
    assert {e["to"] for e in affected if e.get("role") == "component"} == {
        ids[k] for k in ("масса", "объём", "форма")}
    act(store, "delete_node", studyId=study["id"], nodeId=cid)


def resistance_probe(store, evidence):
    """Конечный контрпример: общий посредник теряет привязку двух смыслов."""
    study = current(store)
    sid = study["id"]
    ids = {n["label"]: n["id"] for n in study["nodes"]}
    original = json.loads(json.dumps(study))
    temporary = ["сопротивление", "деформация", "разрушение"]
    assert not any(label in ids for label in temporary)
    for label in temporary:
        ids[label] = add_node(store, sid, label)
    for a, b in (("твёрдость", "сопротивление"), ("прочность", "сопротивление"),
                 ("сопротивление", "деформация"), ("сопротивление", "разрушение")):
        connect(store, sid, ids, a, b, "аспект")
    export(store, evidence)
    for label in temporary:
        act(store, "delete_node", studyId=sid, nodeId=ids[label])
    assert current(store) == original


def prune(store, evidence):
    study = current(store)
    sid = study["id"]
    original = json.loads(json.dumps(study))
    ids = {n["label"]: n["id"] for n in study["nodes"]}
    by_id = {n["id"]: n["label"] for n in study["nodes"]}
    wanted = [(a, b) for a, targets in SELECTED.items() for b in targets.split()]
    labels = {label for pair in wanted for label in pair}
    assert set(ids) == labels | set(EXCLUSIONS), "Ожидался исходный граф 49/114"
    audit = {"sourceRevision": store.read()["revision"], "studyId": sid,
             "removedNodes": [], "removedEdges": [], "movedEdges": [], "addedEdges": []}
    retained = set()
    for a, b in wanted:
        existing = next((e for e in original["edges"] if e["from"] == ids[a]
                         and e["to"] == ids[b] and e["type"] == "аспект"), None)
        if existing:
            retained.add(existing["id"])
            continue
        # Перенос из прежней непосредственной связи, если нового ребра ещё нет.
        old = next((e for e in original["edges"] if e["to"] == ids[b]
                    and e["type"] == "аспект" and e["id"] not in retained
                    and ((a == "характеристика" and e["from"] == ids["камень"])
                         or (a == "состав" and e["from"] == ids["материал"]))), None)
        if old:
            act(store, "edit_edge", studyId=sid, edgeId=old["id"], **{
                "from": ids[a], "to": ids[b], "type": "аспект", "role": "relation", "notes": ""})
            retained.add(old["id"])
            audit["movedEdges"].append({"id": old["id"], "before": [by_id[old["from"]], b],
                                         "after": [a, b], "reason": "Один маршрут вместо прямой связи"})
        else:
            connect(store, sid, ids, a, b, "аспект")
            audit["addedEdges"].append({"from": a, "to": b, "reason": "Функция выбранного разложения"})
    for e in original["edges"]:
        if e["id"] not in retained:
            a, b = by_id[e["from"]], by_id[e["to"]]
            reason = EXCLUSIONS.get(a) or EXCLUSIONS.get(b)
            if not reason:
                reason = "Дублирующий маршрут, обратная классификация или невыраженная привязка параметра; не входит в SELECTED"
            act(store, "delete_edge", studyId=sid, edgeId=e["id"])
            audit["removedEdges"].append({"id": e["id"], "from": a, "to": b,
                                          "type": e["type"], "reason": reason})
    for label, reason in EXCLUSIONS.items():
        act(store, "delete_node", studyId=sid, nodeId=ids[label])
        audit["removedNodes"].append({"id": ids[label], "label": label, "reason": reason})
    act(store, "edit_study", studyId=sid, title="Камень — K001",
        description="Выбранная декомпозиция возможного описания камня: один путь на функцию. Аспект раскрывает позицию описания по пути от корня, не значение экземпляра. Это ручная гипотеза, не универсальная классификация. Функции и ограничения: docs/discussion/conclusion.md §12.4.")
    audit["targetRevision"] = store.read()["revision"]
    audit["selected"] = SELECTED
    final = current(store)
    assert len(final["nodes"]) == len(labels)
    actual = {(by_id[e["from"]], by_id[e["to"]]) for e in final["edges"]}
    assert actual == set(wanted) and len(final["edges"]) == len(wanted)
    write(evidence, audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("baseline", "expand", "discard-grouping", "probe", "prune", "export"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    store = Store(args.db)
    if args.phase == "baseline":
        baseline(store)
    elif args.phase == "expand":
        expand(store)
    elif args.phase == "discard-grouping":
        discard_grouping(store)
    elif args.phase == "probe":
        if args.evidence is None:
            parser.error("Для probe требуется отдельный --evidence")
        resistance_probe(store, args.evidence)
    elif args.phase == "prune":
        if args.evidence is None:
            parser.error("Для prune требуется отдельный --evidence")
        prune(store, args.evidence)
    export(store, args.output)


if __name__ == "__main__":
    main()
