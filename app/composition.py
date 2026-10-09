"""Explicit structure and operator-confirmed substitution; never semantic inference."""
from __future__ import annotations

import copy

from app.store import Invalid, clean, lookup, now, uid

COLLECTIONS = ("nodes", "edges", "designations", "substitutions")
OPERATIONS = ("study", "node", "edge", "designation", "substitution", "match", "delete_node", "delete_edge", "delete_designation", "delete_substitution")


def structure(node):
    return node.get("structure", "concept")


def edge_role(edge):
    return edge.get("role", "relation")


def display(node):
    return node.get("label") or f"α · {node['id'][:8]}"


def metadata(study):
    return {k: copy.deepcopy(v) for k, v in study.items() if k not in COLLECTIONS}


def collection(operation):
    return {"node": "nodes", "edge": "edges", "designation": "designations", "substitution": "substitutions"}[operation.removeprefix("delete_")]


def invalidate_matches(state, sid):
    for match in state["matches"]:
        if sid in (match["leftStudy"], match["rightStudy"]) and match["status"] != "pending":
            match["status"] = "pending"
            match["reason"] = "Структура изменилась; требуется повторная проверка. Ранее: " + match.get("reason", "")[:30000]


def reachable_components(study, start):
    adjacency = {}
    for edge in study["edges"]:
        if edge_role(edge) == "component":
            adjacency.setdefault(edge["from"], []).append(edge["to"])
    seen, pending = set(), [start]
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        pending.extend(adjacency.get(identity, []))
    return seen


def replacement_preview(state, sid, source_id, target_id):
    study = lookup(state["studies"], sid, "исследование")
    source = lookup(study["nodes"], source_id, "исходный концепт")
    target = lookup(study["nodes"], target_id, "выражающая комбинация")
    problems = []
    if source_id == target_id or structure(source) != "concept" or structure(target) != "combination":
        problems.append("Замещение допускается от отдельного концепта к другой комбинации этого исследования.")
    if not any(edge_role(e) == "component" and e["from"] == target_id for e in study["edges"]):
        problems.append("У выражающей комбинации нет компонентов. Сначала задайте состав; эквивалентность пустому элементу не проверяется.")
    if source_id in reachable_components(study, target_id):
        problems.append("Комбинация включает замещаемый концепт, непосредственно или через вложенный состав. Замещение создало бы самоопределение; сначала уточните состав.")
    incident = [e for e in study["edges"] if source_id in (e["from"], e["to"])]
    for edge in incident:
        if target_id in (edge["from"], edge["to"]) or edge["from"] == edge["to"]:
            problems.append(f"Связь {edge['id']} после переноса стала бы самоссылкой. Решите её значение отдельно; автоматический перенос запрещён.")
    matches = [m for m in state["matches"] if source_id in (m["leftNode"], m["rightNode"])]
    existing_pairs = {frozenset((m["leftNode"], m["rightNode"])) for m in state["matches"] if m not in matches}
    for match in matches:
        remapped = frozenset(target_id if i == source_id else i for i in (match["leftNode"], match["rightNode"]))
        if remapped in existing_pairs:
            problems.append("Перенос межисследовательского соответствия совпадает с существующим решением для комбинации. Нужно отдельное решение о конфликте.")
    if any(r.get("status") == "active" and r["targetId"] == source_id for r in study.get("substitutions", [])):
        problems.append("Исходный узел используется активным замещением. Сначала отмените его.")
    return {"source": copy.deepcopy(source), "target": copy.deepcopy(target), "edges": copy.deepcopy(incident), "matches": copy.deepcopy(matches), "designations": copy.deepcopy([d for d in study.get("designations", []) if d["target"] == source_id]), "rootChanges": study["rootId"] == source_id, "problems": problems, "canReplace": not problems}


def context(state, study, source_id, target_id):
    return {"target": copy.deepcopy(lookup(study["nodes"], target_id, "комбинация")), "edges": copy.deepcopy([e for e in study["edges"] if source_id in (e["from"], e["to"]) or target_id in (e["from"], e["to"])]), "designations": copy.deepcopy([d for d in study.get("designations", []) if d["target"] in (source_id, target_id)]), "matches": copy.deepcopy([m for m in state["matches"] if study["id"] in (m["leftStudy"], m["rightStudy"])]), "rootId": study["rootId"]}


def replace(state, data):
    sid, source_id, target_id = data.get("studyId"), data.get("sourceId"), data.get("targetId")
    preview = replacement_preview(state, sid, source_id, target_id)
    if preview["problems"]:
        raise Invalid("Замещение не выполнено: " + " ".join(preview["problems"]))
    if data.get("confirmed") is not True:
        raise Invalid("Подтвердите эквивалентность концепта комбинации вручную.")
    reason = clean(data.get("reason", ""), "обоснование эквивалентности", True)
    study = lookup(state["studies"], sid, "исследование")
    source = lookup(study["nodes"], source_id, "концепт")
    target = lookup(study["nodes"], target_id, "комбинация")
    before = context(state, study, source_id, target_id)
    before["source"] = copy.deepcopy(source)
    before["sourceIndex"] = study["nodes"].index(source)
    origin = {"studyId": sid, "studyTitle": study["title"], "nodeId": source_id, "capturedAt": now(), "operation": "substitution", "snapshot": copy.deepcopy(source)}
    target["origins"].append(origin)
    for edge in study["edges"]:
        for endpoint in ("from", "to"):
            if edge[endpoint] == source_id:
                edge[endpoint] = target_id
    for designation in study.get("designations", []):
        if designation["target"] == source_id:
            designation["target"] = target_id
    study.setdefault("designations", []).append({"id": uid(), "text": source["label"], "target": target_id, "notes": reason, "source": "Подтверждённое оператором замещение", "origins": [copy.deepcopy(origin)], "createdAt": now()})
    for match in state["matches"]:
        for endpoint in ("leftNode", "rightNode"):
            if match[endpoint] == source_id:
                match[endpoint] = target_id
    if study["rootId"] == source_id:
        study["rootId"] = target_id
    study["nodes"].remove(source)
    invalidate_matches(state, sid)
    record = {"id": uid(), "sourceId": source_id, "targetId": target_id, "status": "active", "reason": reason, "time": now(), "before": before, "after": context(state, study, source_id, target_id)}
    study.setdefault("substitutions", []).append(record)
    return {"studyId": sid, "nodeId": target_id, "substitutionId": record["id"]}, f"Замещён «{display(source)}» комбинацией «{display(target)}»; исходные данные сохранены"


def restore_replacement(state, data):
    study = lookup(state["studies"], data.get("studyId"), "исследование")
    record = lookup(study.get("substitutions", []), data.get("substitutionId"), "замещение")
    if record["status"] != "active":
        raise Invalid("Замещение уже отменено или является архивным происхождением.")
    source_id, target_id = record["sourceId"], record["targetId"]
    if any(n["id"] == source_id for n in study["nodes"]):
        raise Invalid("Исходный ID уже используется; обратное замещение неоднозначно.")
    if context(state, study, source_id, target_id) != record["after"]:
        raise Invalid("Затронутый контекст изменился после замещения. Автоматическая отмена неоднозначна; можно восстановить полную версию в истории или решить новые изменения вручную.")
    before = record["before"]
    target = lookup(study["nodes"], target_id, "комбинация")
    target.clear()
    target.update(copy.deepcopy(before["target"]))
    study["nodes"].insert(min(before.get("sourceIndex", len(study["nodes"])), len(study["nodes"])), copy.deepcopy(before["source"]))
    for key in ("edges", "designations"):
        affected = {obj["id"] for obj in record["after"][key]} | {obj["id"] for obj in before[key]}
        originals = {obj["id"]: obj for obj in before[key]}
        study[key] = [copy.deepcopy(originals[obj["id"]]) if obj["id"] in originals else obj for obj in study.get(key, []) if obj["id"] not in affected or obj["id"] in originals]
    original_matches = {m["id"]: m for m in before["matches"]}
    state["matches"] = [copy.deepcopy(original_matches[m["id"]]) if m["id"] in original_matches else m for m in state["matches"]]
    study["rootId"] = before["rootId"]
    record.update(status="restored", restoredAt=now())
    invalidate_matches(state, study["id"])
    return {"studyId": study["id"], "nodeId": source_id}, "Замещение отменено; исходный концепт, связи и обозначения восстановлены"
