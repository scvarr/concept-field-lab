"""Operator-approved quotient of immutable source graphs; no semantic inference.

Candidates are derived visual data. Traversals always run in each original
source before projecting nodes; they never walk a mixture of source edges.
"""
from __future__ import annotations

import copy
import json
import math
from collections import Counter, defaultdict, deque
from itertools import combinations

from app.store import Invalid, clean, lookup, now, uid
from app.composition import structure, edge_role

COLORS = ["#2563eb", "#d97706", "#16a34a", "#be185d", "#7c3aed", "#0891b2", "#9a3412", "#4d7c0f"]


def reference(sid, nid):
    return json.dumps([sid, nid], ensure_ascii=False, separators=(",", ":"))


def normalized(text):
    return " ".join(text.split()).casefold()


def members(acc):
    return {reference(s["studyId"], n["id"]): (s, n) for s in acc["sources"] for n in s["snapshot"]["nodes"]}


def partition(acc):
    refs = members(acc)
    parent = {r: r for r in refs}
    representatives = {r: s["nodeIds"][n["id"]] for r, (s, n) in refs.items()}
    def root(r):
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r
    for d in acc["decisions"]:
        if d["status"] != "confirmed":
            continue
        joined = d["left"] + d["right"]
        anchor = root(joined[0])
        for r in joined:
            parent[root(r)] = anchor
        representatives[anchor] = d["representativeId"]
    groups = defaultdict(list)
    for r in refs:
        groups[representatives[root(r)]].append(r)
    node_map = {r: gid for gid, rows in groups.items() for r in rows}
    rejections = set()
    for d in acc["decisions"]:
        if d["status"] != "rejected":
            continue
        for a in {node_map[r] for r in d["left"]}:
            for b in {node_map[r] for r in d["right"]}:
                if a == b:
                    raise Invalid("Отождествление противоречит сохранённому решению «разные концепты». Проверьте историю решений.")
                rejections.add(tuple(sorted((a, b))))
    return dict(groups), node_map, rejections


def source_origin(source, item, key):
    return {"studyId": source["studyId"], "studyTitle": source["snapshot"]["title"], key: item["id"],
            "capturedAt": source["addedAt"], "snapshot": copy.deepcopy(item)}


def projection(acc, previous=None):
    refs = members(acc)
    groups, node_map, _ = partition(acc)
    previous_nodes = {n["id"]: n for n in (previous or {}).get("nodes", [])}
    nodes, edges, designations, substitutions = [], [], [], []
    for gid, group in groups.items():
        chosen = next((r for r in group if refs[r][0]["nodeIds"][refs[r][1]["id"]] == gid), group[0])
        source, original = refs[chosen]
        node = {**copy.deepcopy(original), "id": gid,
                "origins": [source_origin(*refs[r], "nodeId") for r in group],
                "createdAt": source["addedAt"]}
        if any(structure(refs[r][1]) == "combination" for r in group):
            node["structure"] = "combination"
        saved = previous_nodes.get(gid)
        point = saved if saved is not None else source["positions"][original["id"]]
        node.update(x=point["x"], y=point["y"])
        if saved is not None and "layoutPinned" in saved:
            node["layoutPinned"] = saved["layoutPinned"]
        elif saved is not None:
            node.pop("layoutPinned", None)
        nodes.append(node)
    for source in acc["sources"]:
        snapshot = source["snapshot"]
        mapped = lambda nid: node_map[reference(source["studyId"], nid)]
        for e in snapshot["edges"]:
            edges.append({**copy.deepcopy(e), "id": source["edgeIds"][e["id"]],
                          "from": mapped(e["from"]), "to": mapped(e["to"]),
                          "accumulationSourceId": source["studyId"],
                          "origins": [source_origin(source, e, "edgeId")]})
        for d in snapshot.get("designations", []):
            designations.append({**copy.deepcopy(d), "id": source["designationIds"][d["id"]],
                                 "target": mapped(d["target"]), "origins": [source_origin(source, d, "designationId")]})
        for item in snapshot.get("substitutions", []):
            substitutions.append({**copy.deepcopy(item), "id": source["substitutionIds"][item["id"]],
                "status": "archived", "targetId": mapped(item["targetId"]),
                "sourceTargetId": item.get("sourceTargetId", item["targetId"]),
                "sourceStudyId": source["studyId"], "sourceRecordId": item["id"]})
    for alias in acc["aliases"]:
        designations.append({"id": alias["id"], "text": alias["text"], "target": node_map[alias["reference"]],
            "notes": alias["notes"], "source": "Рабочий словарь накопления; исходное исследование не изменено",
            "createdAt": alias["time"], "origins": [{"studyId": refs[alias["reference"]][0]["studyId"], "snapshot": copy.deepcopy(alias)}]})
    roots = list(dict.fromkeys(node_map[reference(s["studyId"], s["snapshot"]["rootId"])] for s in acc["sources"]))
    if 'manual' in acc:
        from app.builder import manual
        layer = manual(acc)
        for node in layer['nodes']:
            clone = copy.deepcopy(node)
            saved = previous_nodes.get(node['id'])
            if saved:
                clone.update({k: saved[k] for k in ('x', 'y', 'layoutPinned') if k in saved})
            nodes.append(clone)
        edges.extend(copy.deepcopy(layer['edges']))
        designations.extend(copy.deepcopy(layer['designations']))
    return {"nodes": nodes, "edges": edges, "designations": designations, "substitutions": substitutions,
            "rootIds": roots, "rootId": roots[0]}


def layout(snapshot, existing):
    """Stable source block placement; never relayout already added sources."""
    adjacency = defaultdict(list)
    for e in snapshot["edges"]:
        adjacency[e["from"]].append(e["to"])
    distances, queue = {snapshot["rootId"]: 0}, deque([snapshot["rootId"]])
    while queue:
        n = queue.popleft()
        for target in adjacency[n]:
            if target not in distances:
                distances[target] = distances[n] + 1
                queue.append(target)
    layers = defaultdict(list)
    farthest = max(distances.values(), default=0)
    for n in snapshot["nodes"]:
        layers[distances.get(n["id"], farthest + 1)].append(n)
    points = {}
    for depth, rows in layers.items():
        for index, n in enumerate(rows):
            points[n["id"]] = {"x": n.get("x", depth * 260), "y": n.get("y", (index - (len(rows)-1)/2)*90)}
    minimum_x = min(p["x"] for p in points.values())
    maximum_x = max(p["x"] for p in points.values())
    if existing:
        dx = max(n["x"] for n in existing) + 420 - minimum_x
        dy = 0
        if maximum_x + dx > 100000:
            dx = -minimum_x
            dy = max(n["y"] for n in existing) + 260 - min(p["y"] for p in points.values())
    else:
        dx, dy = -minimum_x, 0
    result = {nid: {"x": p["x"] + dx, "y": p["y"] + dy} for nid, p in points.items()}
    if any(abs(p[k]) > 100000 for p in result.values() for k in ("x", "y")):
        raise Invalid("Новый блок выходит за предел координат редактора ±100000. Используйте меньший исходный фрагмент или расположите существующие блоки компактнее.")
    return result


def add_source(state, study, sid):
    source = lookup(state["studies"], sid, "исходное исследование")
    if source.get("accumulation"):
        raise Invalid("Добавляйте независимые исследования. Накопление импортируется и продолжается целиком.")
    acc = study["accumulation"]
    if any(s["studyId"] == sid for s in acc["sources"]):
        raise Invalid("Это исходное исследование уже добавлено; решения и снимок сохранены.")
    snapshot = copy.deepcopy(source)
    captured = {"studyId": sid, "snapshot": snapshot, "addedAt": now(),
        "nodeIds": {n["id"]: uid() for n in snapshot["nodes"]},
        "edgeIds": {e["id"]: uid() for e in snapshot["edges"]},
        "designationIds": {d["id"]: uid() for d in snapshot.get("designations", [])},
        "substitutionIds": {s["id"]: uid() for s in snapshot.get("substitutions", [])},
        "positions": layout(snapshot, study["nodes"])}
    acc["sources"].append(captured)
    study.update(projection(acc, study))


def operate(state, action, data):
    if action == "create_accumulation":
        source_ids = data.get("sourceStudyIds")
        if not isinstance(source_ids, list) or not source_ids or len(set(source_ids)) != len(source_ids):
            raise Invalid("Выберите одно или несколько независимых исследований без повторов.")
        study = {"id": uid(), "title": clean(data.get("title"), "название полотна", True, 1000),
                 "description": "Накопление ручных решений. Цветные рёбра сохраняют источник; их произвольное сочетание не подтверждает смысловой маршрут.",
                 "nodes": [], "edges": [], "archived": False, "createdAt": now(),
                 "accumulation": {"version": 1, "sources": [], "decisions": [], "aliases": [], "camera": None}}
        for sid in source_ids:
            add_source(state, study, sid)
        state["studies"].append(study)
        return {"studyId": study["id"], "nodeId": study["rootId"]}, f"Создано накопительное полотно «{study['title']}»"
    study = lookup(state["studies"], data.get("studyId"), "накопительное полотно")
    acc = study.get("accumulation")
    if acc is None:
        raise Invalid("Выберите накопительное полотно.")
    if action == "accumulation_add_source":
        add_source(state, study, data.get("sourceStudyId"))
        return {"studyId": study["id"]}, "Добавлен независимый исходный граф; прежние решения сохранены"
    if action == "accumulation_camera":
        check_camera(data.get("camera"))
        acc["camera"] = copy.deepcopy(data["camera"])
        return {}, "Сохранена камера накопительного полотна"
    if action == "accumulation_alias":
        ref = data.get("reference")
        if ref not in members(acc):
            raise Invalid("Выберите исходное представление узла.")
        text = clean(data.get("text"), "обозначение", True, 1000)
        if any(a["reference"] == ref and a["text"] == text for a in acc["aliases"]):
            raise Invalid("Это обозначение уже есть в рабочем словаре.")
        acc["aliases"].append({"id": uid(), "reference": ref, "text": text, "notes": clean(data.get("notes", ""), "пояснение"), "time": now()})
        study.update(projection(acc, study))
        return {}, "Добавлено обозначение рабочего словаря; исходник сохранён"
    if action != "accumulation_decide":
        raise Invalid("Неизвестная операция накопления.")
    groups, _, rejections = partition(acc)
    left, right = data.get("leftNode"), data.get("rightNode")
    if left not in groups or right not in groups or left == right:
        raise Invalid("Выберите два разных узла текущего полотна.")
    status = data.get("status")
    if status not in ("confirmed", "rejected", "pending"):
        raise Invalid("Решение: confirmed, rejected или pending.")
    if status == "pending" and tuple(sorted((left, right))) in rejections:
        raise Invalid("Пара уже признана разными концептами. Неопределённость не отменяет сохранённый отказ; для пересмотра восстановите подходящую версию истории.")
    reason = clean(data.get("reason", ""), "обоснование", status != "pending")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or any(not isinstance(x, dict) for x in evidence):
        raise Invalid("Неверное свидетельство выбора пары.")
    decision = {"id": uid(), "time": now(), "status": status, "reason": reason,
                "left": list(groups[left]), "right": list(groups[right]),
                "representativeId": left, "evidence": copy.deepcopy(evidence)}
    acc["decisions"].append(decision)
    # Store transaction validates before write: conflict never partially persists.
    study.update(projection(acc, study))
    return {"nodeId": left, "decisionId": decision["id"]}, f"Решение накопления: {status}; исходные рёбра сохранены"


def check_camera(camera):
    if camera is None:
        return
    if not isinstance(camera, dict) or set(camera) != {"x", "y", "scale"}:
        raise Invalid("Камера содержит x, y и scale.")
    if any(not isinstance(camera[k], (int, float)) or isinstance(camera[k], bool) or not math.isfinite(camera[k]) for k in camera):
        raise Invalid("Координаты камеры должны быть конечными числами.")
    if not .002 <= camera["scale"] <= 4 or any(abs(camera[k]) > 1e7 for k in ("x", "y")):
        raise Invalid("Камера вне диапазона редактора.")


def validate_accumulation(study):
    from app.store import validate
    acc = study["accumulation"]
    if not isinstance(acc, dict) or acc.get("version") != 1 or any(not isinstance(acc.get(k), list) for k in ("sources", "decisions", "aliases")):
        raise Invalid("Неверные метаданные накопления.")
    if not acc["sources"]:
        raise Invalid("В накоплении нужен хотя бы один исходный граф.")
    seen_sources, reserved = set(), set()
    for s in acc["sources"]:
        if not isinstance(s, dict) or not isinstance(s.get("snapshot"), dict) or s.get("studyId") in seen_sources:
            raise Invalid("Повторяющийся или неверный исходник накопления.")
        snapshot = s["snapshot"]
        if snapshot.get("id") != s.get("studyId") or snapshot.get("accumulation"):
            raise Invalid("Снимок должен быть независимым исходным исследованием.")
        seen_sources.add(s["studyId"])
        clean(s.get("addedAt"), "время добавления", True)
        validate({"studies": [snapshot], "matches": [], "imports": [], "proposals": []})
        for mapping, collection in (("nodeIds", "nodes"), ("edgeIds", "edges"), ("designationIds", "designations"), ("substitutionIds", "substitutions")):
            table = s.get(mapping)
            if not isinstance(table, dict) or set(table) != {x["id"] for x in snapshot.get(collection, [])}:
                raise Invalid("Неверная карта объектов исходника накопления.")
            for value in table.values():
                clean(value, "ID копии", True, 200)
                if value in reserved:
                    raise Invalid("Копии исходных объектов имеют разные ID.")
                reserved.add(value)
        if not isinstance(s.get("positions"), dict) or set(s["positions"]) != set(s["nodeIds"]):
            raise Invalid("Неверные исходные позиции блока.")
        for point in s["positions"].values():
            if not isinstance(point, dict) or set(point) != {"x", "y"} or any(not isinstance(point[k], (int, float)) or isinstance(point[k], bool) or not math.isfinite(point[k]) or abs(point[k]) > 100000 for k in point):
                raise Invalid("Позиции накопления должны быть конечными координатами ±100000.")
    refs = members(acc)
    decision_ids = set()
    for d in acc["decisions"]:
        if not isinstance(d, dict) or d.get("status") not in ("pending", "confirmed", "rejected"):
            raise Invalid("Неверное решение накопления.")
        clean(d.get("id"), "ID решения", True, 200)
        if d["id"] in decision_ids:
            raise Invalid("Повторяющийся ID решения накопления.")
        decision_ids.add(d["id"])
        clean(d.get("time"), "время решения", True)
        clean(d.get("reason"), "обоснование", d["status"] != "pending")
        for key in ("left", "right"):
            rows = d.get(key)
            if not isinstance(rows, list) or not rows or any(not isinstance(r, str) or r not in refs for r in rows) or len(set(rows)) != len(rows):
                raise Invalid("Решение ссылается на отсутствующее исходное представление.")
        if set(d["left"]) & set(d["right"]):
            raise Invalid("Стороны решения должны различаться.")
        local_ids = {refs[r][0]["nodeIds"][refs[r][1]["id"]] for r in d["left"] + d["right"]}
        if d.get("representativeId") not in local_ids:
            raise Invalid("Представитель решения должен происходить из выбранной пары.")
        if not isinstance(d.get("evidence"), list):
            raise Invalid("Свидетельства решения должны быть списком.")
    alias_ids = set()
    for a in acc["aliases"]:
        if not isinstance(a, dict) or a.get("reference") not in refs:
            raise Invalid("Обозначение накопления ссылается на отсутствующее представление.")
        clean(a.get("id"), "ID обозначения", True, 200)
        if a["id"] in alias_ids or a["id"] in reserved:
            raise Invalid("ID рабочего обозначения должен быть уникален.")
        alias_ids.add(a["id"])
        clean(a.get("text"), "обозначение", True, 1000)
        clean(a.get("notes"), "пояснение")
        clean(a.get("time"), "время обозначения", True)
    check_camera(acc.get("camera"))
    if "lastLayout" in acc:
        from app.geometry import validate_record
        validate_record(acc["lastLayout"])
    for n in study["nodes"]:
        if any(not isinstance(n.get(k), (int, float)) or isinstance(n[k], bool) or not math.isfinite(n[k]) or abs(n[k]) > 100000 for k in ("x", "y")):
            raise Invalid("Координаты узла накопления должны быть конечными числами ±100000.")
    expected = projection(acc, study)
    for key in ("nodes", "edges", "designations", "substitutions", "rootIds", "rootId"):
        if study.get(key) != expected[key]:
            raise Invalid(f"Накопление не совпадает с исходниками и решениями: {key}. Импортируйте полотно целиком.")


def lexical_index(study, basis="designation", source_ids=None, status="all", query="", limit=2000):
    if basis not in ("designation", "label", "both") or status not in ("all", "pending", "confirmed", "rejected"):
        raise Invalid("Неверный источник или статус индекса совпадений.")
    acc = study["accumulation"]
    refs = members(acc)
    groups, node_map, rejected = partition(acc)
    selected = set(source_ids or [s["studyId"] for s in acc["sources"]])
    buckets = defaultdict(dict)
    for source in acc["sources"]:
        sid = source["studyId"]
        if sid not in selected:
            continue
        values = []
        if basis in ("designation", "both"):
            values += [("designation", d["text"], reference(sid, d["target"])) for d in source["snapshot"].get("designations", [])]
            values += [("designation", a["text"], a["reference"]) for a in acc["aliases"] if refs[a["reference"]][0]["studyId"] == sid]
        if basis in ("label", "both"):
            values += [("label", n["label"], reference(sid, n["id"])) for n in source["snapshot"]["nodes"] if n["label"]]
        for kind, text, ref in values:
            term = normalized(text)
            if normalized(query) not in term:
                continue
            # Even "both" keeps two visibly distinct lexical sources.
            buckets[(kind, term)][ref] = text
    entries, candidates = [], {}
    truncated = False
    for (kind, term), rows in sorted(buckets.items()):
        if len(rows) < 2:
            continue
        by_group = defaultdict(Counter)
        per_source = Counter()
        for r in rows:
            sid = refs[r][0]["studyId"]
            by_group[node_map[r]][sid] += 1
            per_source[sid] += 1
        count_cross = lambda counts: (sum(counts.values())**2 - sum(v*v for v in counts.values()))//2
        total = count_cross(per_source)
        confirmed = sum(count_cross(c) for c in by_group.values())
        rejected_count = sum(sum(by_group[a].values())*sum(by_group[b].values()) - sum(v*by_group[b][s] for s,v in by_group[a].items())
                             for a,b in rejected if a in by_group and b in by_group)
        counts = {"confirmed": confirmed, "rejected": rejected_count, "pending": total - confirmed - rejected_count}
        if status != "all" and not counts[status]:
            continue
        entry = {"key": kind+":"+term, "basis": kind, "term": next(iter(rows.values())),
                 "nodeIds": list(by_group), "references": list(rows), "nodes": len(by_group),
                 "representations": len(rows), "sources": len(per_source), "counts": counts}
        entries.append(entry)
        if status not in ("all", "pending") or not counts["pending"]:
            continue
        # Bound only derived visual pairs. Index statistics remain exact.
        for a,b in combinations(by_group, 2):
            if len(candidates) >= limit:
                truncated = True
                break
            pair = tuple(sorted((a,b)))
            if pair in rejected:
                continue
            ca, cb = by_group[a], by_group[b]
            if sum(ca.values())*sum(cb.values()) == sum(v*cb[s] for s,v in ca.items()):
                continue
            if status not in ("all", "pending"):
                continue
            item = candidates.setdefault(pair, {"id": "candidate:"+a+":"+b, "from": a, "to": b,
                                                "visualOnly": True, "evidence": []})
            item["evidence"].append({"basis": kind, "term": entry["term"], "indexKey": entry["key"]})
    return {"groups": entries, "candidates": list(candidates.values()), "candidateLimit": limit,
            "candidatesTruncated": truncated, "sourceCount": len(acc["sources"]),
            "sources": [{"id": s["studyId"], "title": s["snapshot"]["title"], "color": COLORS[i%len(COLORS)]} for i,s in enumerate(acc["sources"])],
            "decisions": copy.deepcopy(acc["decisions"]), "members": groups}


def neighbourhood(study, node_id, depth=1, source_ids=None, node_limit=150, edge_limit=400):
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
        raise Invalid("Глубина инспектора — целое число от 0.")
    acc = study["accumulation"]
    groups, node_map, _ = partition(acc)
    if node_id not in {n['id'] for n in study['nodes']}:
        raise Invalid("Узел отсутствует на накопительном полотне.")
    selected = set(source_ids or [s["studyId"] for s in acc["sources"]])
    seen_nodes, seen_edges, source_counts = set(), set(), []
    for source in acc["sources"]:
        sid = source["studyId"]
        if sid not in selected:
            continue
        snapshot = source["snapshot"]
        anchors = {n["id"] for n in snapshot["nodes"] if node_map[reference(sid,n["id"])] == node_id}
        if not anchors:
            continue
        adj = defaultdict(list)
        for e in snapshot["edges"]:
            adj[e["from"]].append(e["to"])
            adj[e["to"]].append(e["from"])
        distances = {n: 0 for n in anchors}
        queue = deque(anchors)
        while queue:
            n = queue.popleft()
            if distances[n] >= depth:
                continue
            for target in adj[n]:
                if target not in distances:
                    distances[target] = distances[n] + 1
                    queue.append(target)
        edges = [e for e in snapshot["edges"] if e["from"] in distances and e["to"] in distances]
        seen_nodes.update(node_map[reference(sid,n)] for n in distances)
        seen_edges.update(source["edgeIds"][e["id"]] for e in edges)
        source_counts.append({"sourceId": sid, "nodes": len(distances), "edges": len(edges)})
    # Each manual definition is also inspected separately, never as a mixed route.
    from app.builder import manual
    layer = manual(acc)
    for draft in acc.get('definitionDrafts', []):
        local_edges = [e for e in layer['edges'] if e['definitionId'] == draft['id']]
        local_ids = {n['id'] for n in layer['nodes'] if n['definitionId'] == draft['id']}
        local_ids.update(v for e in local_edges for v in (e['from'], e['to']))
        if node_id not in local_ids or source_ids:
            continue
        distances = {node_id: 0}
        queue = deque([node_id])
        while queue:
            n = queue.popleft()
            if distances[n] >= depth:
                continue
            for e in local_edges:
                if n in (e['from'], e['to']):
                    target = e['to'] if e['from'] == n else e['from']
                    if target not in distances:
                        distances[target] = distances[n] + 1
                        queue.append(target)
        seen_nodes.update(distances)
        seen_edges.update(e['id'] for e in local_edges if e['from'] in distances and e['to'] in distances)
        source_counts.append({'sourceId': draft['id'], 'nodes': len(distances), 'edges': len(local_edges)})
    # Focus stays visible even if the selected source has no representation.
    seen_nodes.add(node_id)
    all_nodes = {n["id"]: n for n in study["nodes"]}
    ordered = [node_id] + sorted(seen_nodes - {node_id})
    shown_ids = set(ordered[:node_limit])
    edges = [e for e in study["edges"] if e["id"] in seen_edges and e["from"] in shown_ids and e["to"] in shown_ids]
    return {"nodes": [copy.deepcopy(all_nodes[n]) for n in ordered[:node_limit]], "edges": copy.deepcopy(edges[:edge_limit]),
            "totalNodes": len(seen_nodes), "totalEdges": len(seen_edges), "nodeLimit": node_limit, "edgeLimit": edge_limit,
            "truncated": len(seen_nodes) > node_limit or len(seen_edges) > edge_limit or len(edges) < len(seen_edges),
            "sourceCounts": source_counts, "traversal": "Каждый исходник обойдён отдельно до проекции; вспомогательные кандидаты исключены."}
