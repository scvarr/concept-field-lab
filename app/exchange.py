"""Versioned graph exchange, neighbourhoods, structural diffs and reviewed patches."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import deque

from app.store import FORMAT, VERSION, Invalid, fields, lookup, now, uid, validate
from app.composition import COLLECTIONS, OPERATIONS, collection, edge_role, metadata


def envelope(kind, **values):
    return {"format": FORMAT, "version": VERSION, "kind": kind, **values}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_document(document):
    if not isinstance(document, dict) or document.get("format") != FORMAT or document.get("version") not in (1, VERSION):
        raise Invalid("Ожидается JSON concept-field-graph версии 1 или 2.")
    kind = document.get("kind")
    if kind == "changes":
        changes = document.get("changes")
        if not isinstance(changes, list) or len(changes) > 100000:
            raise Invalid("Нужен список changes (до 100000 кандидатов).")
        for c in changes:
            if not isinstance(c, dict) or c.get("operation") not in OPERATIONS or not isinstance(c.get("value"), dict):
                raise Invalid("Некорректный кандидат изменения.")
            if c.get("operation") != "match" and not isinstance(c.get("studyId"), str):
                raise Invalid("Укажите studyId кандидата.")
            if not isinstance(c["value"].get("id"), str) or not c["value"]["id"]:
                raise Invalid("Укажите исходный или новый уникальный id.")
            if c["operation"] == "node":
                fields(c["value"])
        return copy.deepcopy(changes)
    if kind not in ("workspace", "study", "fragment"):
        raise Invalid("Можно импортировать workspace, study, fragment или changes. Diff — отчёт; его соответствия не считаются подтверждёнными.")
    state = document.get("state")
    validate(state)
    from app.journal import expand_history
    latest = None
    for row in expand_history(document):
        validate(row["state"])
        latest = row["state"]
    if latest is not None and latest != state:
        raise Invalid("Последняя версия истории не совпадает с экспортированным состоянием.")
    changes = []
    for s in state["studies"]:
        meta = metadata(s)
        changes.append({"operation": "study", "studyId": s["id"], "value": meta})
        for operation, key in (("node", "nodes"), ("edge", "edges"), ("designation", "designations"), ("substitution", "substitutions")):
            changes.extend({"operation": operation, "studyId": s["id"], "value": copy.deepcopy(obj)} for obj in s.get(key, []))
    changes.extend({"operation": "match", "value": copy.deepcopy(m)} for m in state["matches"])
    return changes


def object_index(state):
    objects = {}
    for s in state["studies"]:
        objects[("study", s["id"], s["id"])] = metadata(s)
        for op, key in (("node", "nodes"), ("edge", "edges"), ("designation", "designations"), ("substitution", "substitutions")):
            for obj in s.get(key, []):
                objects[(op, s["id"], obj["id"])] = obj
    for m in state["matches"]:
        objects[("match", None, m["id"])] = m
    objects["__ids__"] = {key[2]: key for key in objects}
    return objects


def current_value(state, candidate, index=None):
    if index is not None:
        key = (candidate["operation"].removeprefix("delete_"), candidate.get("studyId"), candidate["value"]["id"])
        return index.get(key)
    op = candidate["operation"]
    if op == "match":
        return next((m for m in state["matches"] if m["id"] == candidate["value"]["id"]), None)
    s = next((s for s in state["studies"] if s["id"] == candidate.get("studyId")), None)
    if s is None:
        return None
    if op == "study":
        return metadata(s)
    key = collection(op)
    return next((obj for obj in s.get(key, []) if obj["id"] == candidate["value"]["id"]), None)


def conflict(state, candidate, index=None):
    if index is None:
        index = object_index(state)
    identity = candidate["value"]["id"]
    expected = (candidate["operation"].removeprefix("delete_"), candidate.get("studyId"), identity)
    owner = index["__ids__"].get(identity)
    if owner is not None and owner != expected:
        return True
    current = current_value(state, candidate, index)
    deleting = candidate["operation"].startswith("delete_")
    if current == candidate["value"] and not deleting:
        return False
    if "base" in candidate:
        return current != candidate["base"]
    return current is not None


def stage(state, document):
    changes = parse_document(document)
    fingerprint = hashlib.sha256(canonical({k: v for k, v in document.items() if k != "exportedAt"}).encode()).hexdigest()
    if any(i.get("fingerprint") == fingerprint for i in state["imports"]):
        return {"added": 0, "duplicates": len(changes), "conflicts": 0}
    # Indexed comparison keeps large graph imports linear in graph size.
    objects = object_index(state)
    pending = {canonical({k: p[k] for k in ("operation", "studyId", "value", "base") if k in p}) for p in state["proposals"] if p["status"] == "pending"}
    added = duplicates = conflicts = 0
    source_id = uid()
    seen = set()
    for change in changes:
        key = (change["operation"], change.get("studyId"), change["value"]["id"])
        if key in seen:
            raise Invalid("Один документ содержит несколько изменений одного объекта. Разделите их на последовательные импорты.")
        seen.add(key)
        current = objects.get((key[0].removeprefix("delete_"), key[1], key[2]))
        if document.get("kind") == "fragment" and change["operation"] == "study" and current is not None:
            # An exported neighbourhood has its own root. It must not replace the source study's metadata.
            duplicates += 1
            continue
        signature = canonical({k: change[k] for k in ("operation", "studyId", "value", "base") if k in change})
        deleting = change["operation"].startswith("delete_")
        if (current == change["value"] and not deleting) or (deleting and current is None) or signature in pending:
            duplicates += 1
            continue
        clash = conflict(state, change, objects)
        proposal = {**change, "id": uid(), "status": "pending", "importId": source_id, "stagedAt": now()}
        state["proposals"].append(proposal)
        pending.add(signature)
        added += 1
        conflicts += int(clash)
    state["imports"].append({"id": source_id, "time": now(), "fingerprint": fingerprint, "document": copy.deepcopy(document)})
    return {"added": added, "duplicates": duplicates, "conflicts": conflicts}


def review(state, data):
    ids = data.get("proposalIds")
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise Invalid("Выберите кандидатов без повторов.")
    proposals = {p["id"]: p for p in state["proposals"]}
    if any(i not in proposals for i in ids):
        raise Invalid("Кандидат не найден.")
    selected = [proposals[i] for i in ids]
    if any(p["status"] != "pending" for p in selected):
        raise Invalid("Кандидат уже рассмотрен.")
    if data.get("decision") == "reject":
        for p in selected:
            p.update(status="rejected", reviewedAt=now(), reviewReason=data.get("reason", ""))
        return {"count": len(selected)}
    if data.get("decision") != "accept":
        raise Invalid("Выберите accept или reject.")
    targets = [(p["operation"].removeprefix("delete_"), p.get("studyId"), p["value"]["id"]) for p in selected]
    if len(set(targets)) != len(targets):
        raise Invalid("Выбрано несколько предложений для одного объекта. Сравните их и примите только одно.")
    indexed = object_index(state)
    owners = dict(indexed["__ids__"])
    for p in selected:
        if p["operation"].startswith("delete_"):
            continue
        key = (p["operation"], p.get("studyId"), p["value"]["id"])
        old = owners.get(key[2])
        if old is not None and old != key:
            raise Invalid(f"Конфликт ID {key[2]}: он принадлежит другому объекту или исследованию. Заменой это не разрешается; отклоните кандидат и запросите новый уникальный ID.")
        owners[key[2]] = key
    if any(conflict(state, p, indexed) for p in selected) and data.get("allowConflicts") is not True:
        raise Invalid("Есть конфликты с текущими данными. Сравните версии и явно разрешите замену конфликтующих объектов.")
    order = {"study": 0, "node": 1, "edge": 2, "designation": 3, "substitution": 4, "match": 5, "delete_designation": 6, "delete_edge": 7, "delete_node": 8}
    studies = {s["id"]: s for s in state["studies"]}
    changed_studies = set()
    for p in sorted(selected, key=lambda p: order[p["operation"]]):
        op, value = p["operation"], copy.deepcopy(p["value"])
        if op == "match":
            existing = indexed.get(("match", None, value["id"]))
            # External judgments always require a separate manual semantic decision.
            value["status"] = "pending"
            value["reason"] = "Импортированное соответствие: " + value.get("reason", "")[:40000]
            if existing:
                existing.clear()
                existing.update(value)
            else:
                state["matches"].append(value)
        elif op == "study":
            if value["id"] != p["studyId"]:
                raise Invalid("ID исследования и studyId не совпадают.")
            existing = studies.get(value["id"])
            if existing:
                existing.update(metadata(value))
            else:
                created = {**value, "nodes": [], "edges": []}
                state["studies"].append(created)
                studies[value["id"]] = created
        else:
            s = studies.get(p.get("studyId"))
            if s is None:
                raise Invalid("Сначала примите исследование и зависимости кандидата.")
            key = collection(op)
            s.setdefault(key, [])
            existing = indexed.get((op.removeprefix("delete_"), s["id"], value["id"]))
            if op.startswith("delete_") or existing != value:
                changed_studies.add(s["id"])
            if op.startswith("delete_"):
                if existing:
                    if op == "delete_node":
                        if s["rootId"] == value["id"]:
                            raise Invalid("Нельзя удалять корень.")
                        s["edges"] = [e for e in s["edges"] if value["id"] not in (e["from"], e["to"])]
                        if "designations" in s:
                            s["designations"] = [d for d in s["designations"] if d["target"] != value["id"]]
                        state["matches"] = [m for m in state["matches"] if value["id"] not in (m["leftNode"], m["rightNode"])]
                    s[key].remove(existing)
            else:
                if op == "node":
                    value.setdefault("origins", copy.deepcopy(existing.get("origins", [])) if existing else [])
                    if existing:
                        origins = {canonical(o): o for o in existing.get("origins", [])}
                        origins.update({canonical(o): o for o in value["origins"]})
                        value["origins"] = list(origins.values())
                    value.setdefault("createdAt", now())
                    for field_key in fields(value):
                        value.setdefault(field_key, "")
                elif op in ("edge", "designation"):
                    value.setdefault("origins", [])
                    value.setdefault("notes", "")
                    if op == "edge":
                        value.setdefault("type", "")
                    else:
                        value.setdefault("source", "")
                if existing:
                    existing.clear()
                    existing.update(value)
                else:
                    s[key].append(value)
                indexed[(op, s["id"], value["id"])] = value
        p.update(status="accepted", reviewedAt=now(), reviewReason=data.get("reason", ""), conflictOverride=bool(data.get("allowConflicts")))
    for m in state["matches"]:
        if {m["leftStudy"], m["rightStudy"]} & changed_studies and m["status"] != "pending":
            m["status"] = "pending"
            m["reason"] = "Импорт изменил структуру; требуется повторная проверка. Ранее: " + m.get("reason", "")[:30000]
    validate(state)
    return {"count": len(selected)}


def project_state(state, study_ids, node_ids=None, include_imports=True, import_cache=None):
    result = {"studies": [], "matches": [], "imports": [], "proposals": []}
    included = set()
    for s in state["studies"]:
        if s["id"] not in study_ids:
            continue
        clone = copy.deepcopy(s)
        if node_ids is not None:
            clone["nodes"] = [n for n in clone["nodes"] if n["id"] in node_ids]
            clone["edges"] = [e for e in clone["edges"] if e["from"] in node_ids and e["to"] in node_ids]
            if not clone["nodes"]:
                continue
            if clone["rootId"] not in node_ids:
                clone["rootId"] = next(iter(n["id"] for n in clone["nodes"]))
            for key, reference in (("designations", "target"), ("substitutions", "targetId")):
                if key in clone:
                    clone[key] = [item for item in clone[key] if item[reference] in node_ids]
        included.update(n["id"] for n in clone["nodes"])
        result["studies"].append(clone)
    result["matches"] = [copy.deepcopy(m) for m in state["matches"] if m["leftNode"] in included and m["rightNode"] in included]
    def selected_change(p):
        value = p["value"]
        if p.get("studyId") not in study_ids:
            return False
        if node_ids is None:
            return True
        if p["operation"].removeprefix("delete_") == "edge":
            return value.get("from") in node_ids and value.get("to") in node_ids
        return value.get("id") in node_ids or value.get("target") in node_ids or value.get("targetId") in node_ids
    result["proposals"] = [copy.deepcopy(p) for p in state["proposals"] if selected_change(p)]
    # Export relevant imported provenance, without leaking unrelated investigations into a fragment.
    if include_imports:
        for imported in state["imports"]:
            if import_cache is not None and imported["id"] in import_cache:
                cached = import_cache[imported["id"]]
                if cached:
                    result["imports"].append(cached)
                continue
            doc = imported.get("document")
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") == "changes":
                changes = [copy.deepcopy(c) for c in doc["changes"] if selected_change(c)]
                if not changes:
                    continue
                source = {**doc, "changes": changes}
            else:
                selected_state = project_state(doc["state"], study_ids, node_ids, False)
                if not selected_state["studies"]:
                    continue
                from app.journal import compact_history, expand_history
                projected = [{**h, "state": project_state(h["state"], study_ids, node_ids, False)} for h in expand_history(doc)]
                source = {**doc, "state": selected_state, "historyEncoding": "rfc6902-chain-v1", "history": compact_history(projected)}
            result["imports"].append({**imported, "document": source, "scope": "Filtered to exported study / selected nodes; original fingerprint identifies complete imported document."})
            if import_cache is not None:
                import_cache[imported["id"]] = result["imports"][-1]
    return result


def neighbourhood(study, node_id, depth):
    lookup(study["nodes"], node_id, "элемент")
    if depth is not None and (not isinstance(depth, int) or depth < 0):
        raise Invalid("Глубина — целое число ≥0 или all.")
    adjacency = {n["id"]: [] for n in study["nodes"]}
    for e in study["edges"]:
        adjacency[e["from"]].append(e["to"])
        adjacency[e["to"]].append(e["from"])
    distances = {node_id: 0}
    queue = deque([node_id])
    while queue:
        n = queue.popleft()
        if depth is not None and distances[n] >= depth:
            continue
        for nxt in adjacency[n]:
            if nxt not in distances:
                distances[nxt] = distances[n] + 1
                queue.append(nxt)
    return set(distances)


def graph_export(store, study_id, node_id=None, depth=None):
    with store.lock:
        return _graph_export_locked(store, study_id, node_id, depth)


def _graph_export_locked(store, study_id, node_id, depth):
    from app.journal import compact_history
    current = store.read()["state"]
    study = lookup(current["studies"], study_id, "исследование")
    ids = neighbourhood(study, node_id, depth) if node_id else None
    import_cache = {}
    state = project_state(current, {study_id}, ids, import_cache=import_cache)
    if node_id:
        # Fragment metadata is compatible with importing into its original study.
        fragment = state["studies"][0]
        fragment["rootId"] = node_id
    def history_rows():
        for row in store.iter_snapshots():
            filtered = project_state(row["state"], {study_id}, ids, import_cache=import_cache)
            if filtered["studies"]:
                if node_id and any(n["id"] == node_id for n in filtered["studies"][0]["nodes"]):
                    filtered["studies"][0]["rootId"] = node_id
                yield {**row, "state": filtered}
    return envelope("fragment" if node_id else "study", exportedAt=now(), state=state, historyEncoding="rfc6902-chain-v1", history=compact_history(history_rows()), selection={"studyId": study_id, "nodeId": node_id, "sourceRootId": study["rootId"], "depth": depth if depth is not None else "all", "direction": "both"})


def structural_diff(left, right, matches=None):
    """Explicit ID-based version diff; independent graphs use manual mappings only."""
    left_nodes = {n["id"]: n for n in left["nodes"]}
    right_nodes = {n["id"]: n for n in right["nodes"]}
    pairs = {(i, i) for i in left_nodes.keys() & right_nodes.keys()} if left["id"] == right["id"] else set()
    decisions = []
    for m in matches or []:
        if {m["leftStudy"], m["rightStudy"]} == {left["id"], right["id"]}:
            decisions.append(m)
            if m["status"] == "confirmed":
                a, b = (m["leftNode"], m["rightNode"]) if m["leftStudy"] == left["id"] else (m["rightNode"], m["leftNode"])
                pairs.add((a, b))
    pairs = {(a, b) for a, b in pairs if a in left_nodes and b in right_nodes}
    mapping = {}
    aligned = []
    for a, b in sorted(pairs):
        mapping.setdefault(a, set()).add(b)
        keys = (left_nodes[a].keys() | right_nodes[b].keys()) - {"id"}
        aligned.append({"leftId": a, "rightId": b, "equalFields": sorted(k for k in keys if left_nodes[a].get(k) == right_nodes[b].get(k)), "differences": {k: {"left": left_nodes[a].get(k), "right": right_nodes[b].get(k), "leftPresent": k in left_nodes[a], "rightPresent": k in right_nodes[b]} for k in sorted(keys) if left_nodes[a].get(k) != right_nodes[b].get(k) or (k in left_nodes[a]) != (k in right_nodes[b])}})
    left_edges = {e["id"]: e for e in left["edges"]}
    right_edges = {e["id"]: e for e in right["edges"]}
    relation_alignments = []
    right_signatures = {}
    for e in right["edges"]:
        right_signatures.setdefault((e["from"], e["to"], edge_role(e), e.get("type", ""), e.get("componentRole", "")), []).append(e["id"])
    for e in left["edges"]:
        candidate_ids = set()
        for a in mapping.get(e["from"], set()):
            for b in mapping.get(e["to"], set()):
                candidate_ids.update(right_signatures.get((a, b, edge_role(e), e.get("type", ""), e.get("componentRole", "")), []))
        if candidate_ids:
            relation_alignments.append({"leftEdge": e["id"], "rightEdges": sorted(candidate_ids), "basis": "Confirmed endpoint mapping and exact relation type: structural resemblance only, not a decision to identify relations.", "notesDifferences": {eid: {"left": e.get("notes", ""), "right": right_edges[eid].get("notes", "")} for eid in sorted(candidate_ids) if e.get("notes", "") != right_edges[eid].get("notes", "")}})
    matched_right = {b for _, b in pairs}
    changes = []
    if left["id"] == right["id"]:
        lm = metadata(left)
        rm = metadata(right)
        if lm != rm:
            changes.append({"operation": "study", "studyId": left["id"], "base": lm, "value": rm})
        sets = [("node", left_nodes, right_nodes), ("edge", left_edges, right_edges)]
        for op, key in (("designation", "designations"), ("substitution", "substitutions")):
            sets.append((op, {obj["id"]: obj for obj in left.get(key, [])}, {obj["id"]: obj for obj in right.get(key, [])}))
        for op, la, ra in sets:
            for i in sorted(la.keys() | ra.keys()):
                if i not in ra:
                    if op != "substitution":
                        changes.append({"operation": "delete_" + op, "studyId": left["id"], "base": la[i], "value": {"id": i}})
                elif la.get(i) != ra[i]:
                    changes.append({"operation": op, "studyId": left["id"], "base": la.get(i), "value": ra[i]})
    return envelope("diff", generatedAt=now(), basis="IDs for versions; confirmed manual correspondences for independent studies. Labels are not identity evidence.", left=copy.deepcopy(left), right=copy.deepcopy(right), correspondences=copy.deepcopy(decisions), aligned=aligned, onlyLeft=[i for i in left_nodes if i not in mapping], onlyRight=[i for i in right_nodes if i not in matched_right], relationAlignments=relation_alignments, edges={"onlyLeftIds": sorted(left_edges.keys() - right_edges.keys()), "onlyRightIds": sorted(right_edges.keys() - left_edges.keys()), "changedSameIds": [i for i in left_edges.keys() & right_edges.keys() if left_edges[i] != right_edges[i]]}, versionChanges=envelope("changes", changes=changes) if left["id"] == right["id"] else None)
