"""Atomic geometry-only edits. Algorithms run on detached copies in a worker."""
import copy
import math

from app.store import Invalid, lookup, clean


def points(value):
    if not isinstance(value, dict) or not value or len(value) > 100000:
        raise Invalid("Нужна непустая карта координат (до 100000 узлов).")
    for nid, point in value.items():
        clean(nid, "ID узла", True, 200)
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise Invalid("Позиция содержит только x и y.")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 100000 for v in point.values()):
            raise Invalid("Координаты должны быть конечными числами ±100000.")


def validate_record(record):
    if not isinstance(record, dict) or set(record) != {"before", "after", "algorithm"}:
        raise Invalid("Неверная запись предыдущей раскладки.")
    points(record["before"])
    points(record["after"])
    if set(record["before"]) != set(record["after"]):
        raise Invalid("Предыдущая раскладка должна содержать те же ID.")
    clean(record["algorithm"], "алгоритм", True, 100)


def operate(state, action, data):
    study = lookup(state["studies"], data.get("studyId"), "полотно")
    acc = study.get("accumulation")
    if not acc:
        raise Invalid("Раскладка доступна для накопительного полотна.")
    nodes = {n["id"]: n for n in study["nodes"]}
    if action == "layout_pin":
        ids, pinned = data.get("nodeIds"), data.get("pinned")
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or not isinstance(pinned, bool):
            raise Invalid("Нужен список узлов и признак закрепления.")
        if any(nid not in nodes for nid in ids):
            raise Invalid("Закрепляемый узел отсутствует.")
        for nid in ids:
            if pinned:
                nodes[nid]["layoutPinned"] = True
            else:
                nodes[nid].pop("layoutPinned", None)
        return {"count": len(ids)}, f"{'Закреплено' if pinned else 'Откреплено'} узлов: {len(ids)}"
    if action == "layout_restore":
        record = acc.get("lastLayout")
        if not record:
            raise Invalid("Нет предыдущей раскладки. Более ранние позиции доступны в истории.")
        validate_record(record)
        positions = record["before"]
        if any(nid not in nodes or {k: nodes[nid][k] for k in ("x", "y")} != p for nid, p in record["after"].items()):
            raise Invalid("После раскладки узлы изменились. Используйте историю или новую раскладку.")
        acc.pop("lastLayout")
        detail = f"Возвращено предыдущее расположение: {len(positions)} узлов"
    else:
        positions = data.get("positions")
        points(positions)
        if any(nid not in nodes for nid in positions):
            raise Invalid("Раскладка содержит отсутствующий узел.")
        if any(nodes[nid].get("layoutPinned") for nid in positions):
            raise Invalid("Закреплённые узлы нельзя перемещать раскладкой.")
        algorithm = clean(data.get("algorithm"), "алгоритм", True, 100)
        before = {nid: {k: nodes[nid][k] for k in ("x", "y")} for nid in positions}
        acc["lastLayout"] = {"before": before, "after": copy.deepcopy(positions), "algorithm": algorithm}
        detail = f"Раскладка {algorithm}: {len(positions)} узлов одной операцией"
    for nid, point in positions.items():
        nodes[nid].update(point)
    return {"count": len(positions)}, detail
