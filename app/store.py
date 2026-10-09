"""Transactional workspace snapshots. No semantic inference or external services."""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

FORMAT = "concept-field-graph"
VERSION = 2


class Invalid(ValueError):
    pass


class Conflict(Invalid):
    pass


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(state):
    return zlib.compress(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def decode(payload):
    return json.loads(zlib.decompress(payload) if isinstance(payload, bytes) else payload)


def clean(value, name, required=False, limit=50000):
    if not isinstance(value, str) or len(value) > limit:
        raise Invalid(f"Некорректное поле «{name}» (предел {limit} символов).")
    value = value.strip()
    if required and not value:
        raise Invalid(f"Заполните поле «{name}».")
    return value


def fields(data):
    return {key: clean(data.get(key, ""), key, key == "label" and data.get("structure", "concept") != "combination", 1000 if key in ("label", "kind") else 50000)
            for key in ("label", "kind", "notes", "alternatives", "source")}


def lookup(items, identity, what):
    for item in items:
        if item["id"] == identity:
            return item
    raise Invalid(f"Не найдено: {what}.")


def study_node(state, sid, nid):
    study = lookup(state["studies"], sid, "исследование")
    return study, lookup(study["nodes"], nid, "элемент")


def validate(state):
    """Validate every incoming snapshot, including referential integrity."""
    from app.composition import OPERATIONS, edge_role, structure
    if not isinstance(state, dict) or set(state) != {"studies", "matches", "imports", "proposals"}:
        raise Invalid("Неверная структура рабочего пространства.")
    if not all(isinstance(state[k], list) for k in state):
        raise Invalid("Ожидались списки исследований, соответствий и импортов.")
    identities = set()
    nodes_by_study = {}

    def identity(item):
        if not isinstance(item, dict):
            raise Invalid("Ожидался объект.")
        ident = clean(item.get("id"), "id", True, 200)
        if ident in identities:
            raise Invalid("Идентификаторы должны быть уникальны.")
        identities.add(ident)
        return ident

    for study in state["studies"]:
        sid = identity(study)
        clean(study.get("title"), "название", True, 1000)
        clean(study.get("description", ""), "описание")
        if not isinstance(study.get("archived"), bool):
            raise Invalid("Неверный признак архива.")
        if not isinstance(study.get("nodes"), list) or not isinstance(study.get("edges"), list):
            raise Invalid("Ожидались элементы и отношения.")
        ids = set()
        nodes = {}
        for node in study["nodes"]:
            ids.add(identity(node))
            nodes[node["id"]] = node
            if structure(node) not in ("concept", "combination"):
                raise Invalid("Структурная функция — concept или combination; содержательный тип задаётся отдельно.")
            fields(node)
            if not isinstance(node.get("origins"), list):
                raise Invalid("Неверное происхождение элемента.")
            for origin in node["origins"]:
                if not isinstance(origin, dict) or not isinstance(origin.get("snapshot"), dict):
                    raise Invalid("Происхождение должно содержать снимок исходного элемента.")
        nodes_by_study[sid] = ids
        if study.get("rootId") not in ids:
            raise Invalid("Корневой элемент отсутствует.")
        for edge in study["edges"]:
            identity(edge)
            if edge.get("from") not in ids or edge.get("to") not in ids:
                raise Invalid("Отношение ссылается на отсутствующий элемент.")
            if edge_role(edge) not in ("relation", "component"):
                raise Invalid("Структурная функция соединения — relation или component.")
            if edge_role(edge) == "component" and structure(nodes[edge["from"]]) != "combination":
                raise Invalid("Направленное включение начинается только от комбинации.")
            clean(edge.get("type", ""), "тип отношения", False, 1000)
            clean(edge.get("componentRole", ""), "роль компонента", False, 1000)
            clean(edge.get("notes", ""), "пояснение")
            if not isinstance(edge.get("origins"), list):
                raise Invalid("Неверное происхождение отношения.")
        for key in ("designations", "substitutions"):
            if not isinstance(study.get(key, []), list):
                raise Invalid("Словарь и замещения должны быть списками.")
        for designation in study.get("designations", []):
            identity(designation)
            clean(designation.get("text"), "словесное обозначение", True, 1000)
            if designation.get("target") not in ids:
                raise Invalid("Словарное обозначение ссылается на отсутствующий элемент.")
            for key in ("notes", "source"):
                clean(designation.get(key, ""), key)
            if not isinstance(designation.get("origins"), list):
                raise Invalid("Некорректное происхождение обозначения.")
        for replacement in study.get("substitutions", []):
            identity(replacement)
            if replacement.get("status") not in ("active", "restored", "archived"):
                raise Invalid("Неверный статус замещения.")
            for key in ("before", "after"):
                if not isinstance(replacement.get(key), dict):
                    raise Invalid("Замещение должно сохранять исходный и полученный контекст.")
            for key in ("sourceId", "targetId"):
                clean(replacement.get(key), key, True, 200)
            before, after = replacement["before"], replacement["after"]
            for context in (before, after):
                if not isinstance(context.get("target"), dict) or not all(isinstance(context.get(key), list) for key in ("edges", "designations", "matches")) or not isinstance(context.get("rootId"), str):
                    raise Invalid("Неполный контекст замещения; восстановление не будет безопасным.")
                if context["target"].get("id") != (replacement.get("sourceTargetId", replacement["targetId"]) if replacement["status"] == "archived" else replacement["targetId"]):
                    raise Invalid("ID цели в контексте замещения не совпадает.")
                for key in ("edges", "designations", "matches"):
                    if not all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in context[key]):
                        raise Invalid("Неверные объекты в контексте замещения.")
            if not isinstance(before.get("source"), dict) or before["source"].get("id") != replacement["sourceId"] or structure(before["source"]) != "concept":
                raise Invalid("Замещение должно сохранять исходный концепт и его ID.")
            fields(before["source"])
            if not isinstance(before.get("sourceIndex"), int) or before["sourceIndex"] < 0:
                raise Invalid("Неверная исходная позиция замещённого концепта.")
            if replacement["status"] == "active" and (replacement.get("sourceId") in ids or replacement.get("targetId") not in ids or structure(nodes[replacement["targetId"]]) != "combination"):
                raise Invalid("Активное замещение требует комбинацию назначения и отсутствие замещённого концепта; отмените замещение перед удалением цели.")
    pairs = set()
    for match in state["matches"]:
        identity(match)
        a, b = match.get("leftStudy"), match.get("rightStudy")
        if a == b or match.get("leftNode") not in nodes_by_study.get(a, set()) or match.get("rightNode") not in nodes_by_study.get(b, set()):
            raise Invalid("Соответствие должно связывать элементы разных исследований.")
        pair = tuple(sorted(((a, match["leftNode"]), (b, match["rightNode"]))))
        if pair in pairs:
            raise Invalid("Повторяющееся соответствие.")
        pairs.add(pair)
        if match.get("status") not in ("pending", "confirmed", "rejected"):
            raise Invalid("Неверный статус соответствия.")
        clean(match.get("reason", ""), "обоснование")
    for proposal in state["proposals"]:
        identity(proposal)
        if proposal.get("status") not in ("pending", "accepted", "rejected"):
            raise Invalid("Неверный статус кандидата.")
        if proposal.get("operation") not in OPERATIONS:
            raise Invalid("Неверная операция кандидата.")
        if not isinstance(proposal.get("value"), dict):
            raise Invalid("Неверные данные кандидата.")
        clean(proposal["value"].get("id"), "ID объекта кандидата", True, 200)
        if proposal["operation"] != "match":
            clean(proposal.get("studyId"), "исследование кандидата", True, 200)
    for imported in state["imports"]:
        identity(imported)
        document = imported.get("document")
        if not isinstance(document, dict) or document.get("format") != FORMAT or document.get("version") not in (1, VERSION) or document.get("kind") not in ("workspace", "study", "fragment", "changes"):
            raise Invalid("Некорректный архив происхождения импорта.")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, state TEXT NOT NULL)")
            if not db.execute("SELECT 1 FROM revisions LIMIT 1").fetchone():
                db.execute("INSERT INTO revisions VALUES (0, ?, ?, ?, ?)", (now(), "init", "Создано рабочее пространство", encode({"studies": [], "matches": [], "imports": [], "proposals": []})))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM revisions ORDER BY id DESC LIMIT 1").fetchone()
            return {"revision": row["id"], "state": decode(row["state"])}

    def history(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id, time, action, detail FROM revisions ORDER BY id DESC")]

    def snapshots(self):
        return list(self.iter_snapshots())

    def iter_snapshots(self):
        with self.lock, self.connect() as db:
            for raw in db.execute("SELECT * FROM revisions ORDER BY id"):
                row = dict(raw)
                row["state"] = decode(row["state"])
                yield row

    def export(self):
        from app.journal import compact_with_latest
        history, state = compact_with_latest(self.iter_snapshots())
        return {"format": FORMAT, "version": VERSION, "kind": "workspace", "exportedAt": now(), "state": state, "historyEncoding": "rfc6902-chain-v1", "history": history}

    def parse_import(self, document):
        from app.exchange import parse_document
        parse_document(document)
        return document

    def mutate(self, action, data, revision):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM revisions ORDER BY id DESC LIMIT 1").fetchone()
            if revision != row["id"]:
                raise Conflict("Данные изменились в другой вкладке. Обновите страницу и повторите действие.")
            state = decode(row["state"])
            result = {}
            detail = action
            changed_study = None
            if action == "create_study":
                title = clean(data.get("title"), "название исследования", True, 1000)
                nid, sid = uid(), uid()
                node = {"id": nid, **fields({"label": data.get("label", title), "kind": "слово"}), "origins": [], "createdAt": now()}
                study = {"id": sid, "title": title, "description": clean(data.get("description", ""), "описание"), "rootId": nid, "nodes": [node], "edges": [], "archived": False, "createdAt": now()}
                state["studies"].append(study)
                result = {"studyId": sid, "nodeId": nid}
                detail = f"Создано независимое исследование «{title}»"
            elif action in ("edit_study", "archive_study"):
                study = lookup(state["studies"], data.get("studyId"), "исследование")
                if action == "edit_study":
                    study.update(title=clean(data.get("title"), "название", True, 1000), description=clean(data.get("description", ""), "описание"))
                else:
                    study["archived"] = bool(data.get("archived", True))
                detail = f"Изменено исследование «{study['title']}»"
            elif action in ("add_node", "edit_node", "delete_node", "position"):
                study = lookup(state["studies"], data.get("studyId"), "исследование")
                if action == "add_node":
                    changed_study = study["id"]
                    node = {"id": uid(), **fields(data), "origins": [], "createdAt": now()}
                    if "structure" in data:
                        node["structure"] = data["structure"]
                    study["nodes"].append(node)
                    if data.get("parentId"):
                        lookup(study["nodes"], data["parentId"], "родитель")
                        study["edges"].append({"id": uid(), "from": data["parentId"], "to": node["id"], "type": clean(data.get("relation", ""), "тип отношения", False, 1000), "role": data.get("role", "relation"), "componentRole": clean(data.get("componentRole", ""), "роль компонента", False, 1000), "notes": "", "origins": []})
                    detail = f"Добавлен элемент «{node['label']}» в «{study['title']}»"
                else:
                    node = lookup(study["nodes"], data.get("nodeId"), "элемент")
                    detail = f"{action}: «{node['label']}» в «{study['title']}»"
                    if action == "delete_node":
                        changed_study = study["id"]
                        if study["rootId"] == node["id"]:
                            raise Invalid("Корень нельзя удалить. Можно переименовать или архивировать исследование.")
                        study["nodes"].remove(node)
                        study["edges"] = [e for e in study["edges"] if node["id"] not in (e["from"], e["to"])]
                        if "designations" in study:
                            study["designations"] = [d for d in study["designations"] if d["target"] != node["id"]]
                        state["matches"] = [m for m in state["matches"] if node["id"] not in (m["leftNode"], m["rightNode"])]
                    elif action == "edit_node":
                        new_structure = data.get("structure", node.get("structure", "concept"))
                        changed = fields({**data, "structure": new_structure})
                        if any(node[k] != changed[k] for k in changed) or new_structure != node.get("structure", "concept"):
                            changed_study = study["id"]
                        node.update(changed)
                        if "structure" in node or new_structure != "concept":
                            node["structure"] = new_structure
                    else:
                        x, y = data.get("x"), data.get("y")
                        if not all(isinstance(v, (int, float)) and -100000 <= v <= 100000 for v in (x, y)):
                            raise Invalid("Неверные координаты.")
                        node.update(x=x, y=y)
                result = {"studyId": study["id"], "nodeId": node["id"]}
            elif action in ("add_edge", "edit_edge", "delete_edge"):
                study = lookup(state["studies"], data.get("studyId"), "исследование")
                changed_study = study["id"]
                if action == "add_edge":
                    edge = {"id": uid(), "origins": []}
                    study["edges"].append(edge)
                else:
                    edge = lookup(study["edges"], data.get("edgeId"), "отношение")
                if action == "delete_edge":
                    study["edges"].remove(edge)
                else:
                    lookup(study["nodes"], data.get("from"), "начало отношения")
                    lookup(study["nodes"], data.get("to"), "конец отношения")
                    edge.update({"from": data["from"], "to": data["to"], "type": clean(data.get("type", ""), "тип отношения", False, 1000), "notes": clean(data.get("notes", ""), "пояснение")})
                    if "role" in data:
                        edge["role"] = data["role"]
                    if "componentRole" in data:
                        edge["componentRole"] = clean(data["componentRole"], "роль компонента", False, 1000)
                detail = f"{action}: отношение в «{study['title']}»"
            elif action in ("add_designation", "edit_designation", "delete_designation"):
                study = lookup(state["studies"], data.get("studyId"), "исследование")
                entries = study.setdefault("designations", [])
                if action == "add_designation":
                    entry = {"id": uid(), "createdAt": now(), "origins": []}
                    entries.append(entry)
                else:
                    entry = lookup(entries, data.get("designationId"), "обозначение")
                if action == "delete_designation":
                    entries.remove(entry)
                else:
                    lookup(study["nodes"], data.get("target"), "цель обозначения")
                    entry.update(text=clean(data.get("text"), "обозначение", True, 1000), target=data["target"], notes=clean(data.get("notes", ""), "пояснение"), source=clean(data.get("source", ""), "источник"))
                result = {"designationId": entry["id"]}
                detail = f"{action}: словарь «{study['title']}»"
            elif action == "replace_concept":
                from app.composition import replace
                result, detail = replace(state, data)
            elif action == "restore_substitution":
                from app.composition import restore_replacement
                result, detail = restore_replacement(state, data)
            elif action == "match":
                left, ln = study_node(state, data.get("leftStudy"), data.get("leftNode"))
                right, rn = study_node(state, data.get("rightStudy"), data.get("rightNode"))
                if left["id"] == right["id"]:
                    raise Invalid("Выберите разные исследования.")
                pair = {ln["id"], rn["id"]}
                match = next((m for m in state["matches"] if {m["leftNode"], m["rightNode"]} == pair), None)
                if match is None:
                    match = {"id": uid(), "leftStudy": left["id"], "leftNode": ln["id"], "rightStudy": right["id"], "rightNode": rn["id"]}
                    state["matches"].append(match)
                status = data.get("status", "pending")
                if status not in ("pending", "confirmed", "rejected"):
                    raise Invalid("Неверный статус.")
                match.update(status=status, reason=clean(data.get("reason", ""), "обоснование"), decidedAt=now())
                detail = f"Соответствие «{ln['label']}» ↔ «{rn['label']}»: {status}"
                result = {"matchId": match["id"]}
            elif action == "merge":
                result, detail = self.merge(state, data)
            elif action == "restore":
                target = db.execute("SELECT state FROM revisions WHERE id = ?", (data.get("targetRevision"),)).fetchone()
                if target is None:
                    raise Invalid("Версия отсутствует.")
                state = decode(target[0])
                detail = f"Восстановлена версия {data['targetRevision']}; последующая история сохранена"
            elif action == "import":
                from app.exchange import stage
                result = stage(state, data.get("document"))
                detail = f"Импорт в очередь кандидатов: {result['added']}; повторов: {result['duplicates']}"
            elif action == "review_proposals":
                from app.exchange import review
                result = review(state, data)
                detail = f"Решение по кандидатам: {data.get('decision')}, {result['count']}"
            else:
                raise Invalid("Неизвестная операция.")
            if changed_study:
                for m in state["matches"]:
                    if changed_study in (m["leftStudy"], m["rightStudy"]) and m["status"] != "pending":
                        m["status"] = "pending"
                        m["reason"] = "Структура изменилась; требуется повторная проверка. Ранее: " + m.get("reason", "")[:30000]
            validate(state)
            new_rev = row["id"] + 1
            db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)", (new_rev, now(), action, detail, encode(state)))
            return {"revision": new_rev, "state": state, "result": result}

    def merge(self, state, data):
        from app.composition import structure
        left = lookup(state["studies"], data.get("leftStudy"), "левое исследование")
        right = lookup(state["studies"], data.get("rightStudy"), "правое исследование")
        if left["id"] == right["id"]:
            raise Invalid("Нельзя объединять исследование с собой.")
        selected = data.get("matchIds", [])
        if not isinstance(selected, list) or not selected:
            raise Invalid("Выберите хотя бы одно подтверждённое соответствие.")
        parent = {n["id"]: n["id"] for s in (left, right) for n in s["nodes"]}

        def root(n):
            while parent[n] != n:
                n = parent[n]
            return n

        for identity in selected:
            m = lookup(state["matches"], identity, "соответствие")
            if m["status"] != "confirmed" or {m["leftStudy"], m["rightStudy"]} != {left["id"], right["id"]}:
                raise Invalid("Объединять можно только выбранные подтверждённые соответствия этой пары.")
            parent[root(m["rightNode"])] = root(m["leftNode"])
        groups = {}
        node_map = {}
        for s in (left, right):
            for n in s["nodes"]:
                group = groups.setdefault(root(n["id"]), {"id": uid(), "members": []})
                group["members"].append((s, n))
                node_map[n["id"]] = group["id"]
        nodes = []
        for group in groups.values():
            members = group["members"]
            node = {**copy.deepcopy(members[0][1]), "id": group["id"], "origins": [], "createdAt": now()}
            if any(structure(n) == "combination" for _, n in members):
                node["structure"] = "combination"
            if len(members) > 1:
                for key in ("notes", "alternatives", "source"):
                    node[key] = "\n\n".join(f"[{s['title']}: {n['label']}]\n{n[key]}" for s, n in members if n[key])
                    if len(node[key]) > 50000:
                        raise Invalid("Объединённое поле слишком велико. Сократите пояснения или объединяйте меньшие фрагменты.")
            for s, n in members:
                node["origins"].append({"studyId": s["id"], "studyTitle": s["title"], "nodeId": n["id"], "capturedAt": now(), "snapshot": copy.deepcopy(n)})
            nodes.append(node)
        edges = []
        for s in (left, right):
            for e in s["edges"]:
                edges.append({**copy.deepcopy(e), "id": uid(), "from": node_map[e["from"]], "to": node_map[e["to"]], "origins": [{"studyId": s["id"], "studyTitle": s["title"], "edgeId": e["id"], "snapshot": copy.deepcopy(e)}]})
        merged = {"id": uid(), "title": clean(data.get("title"), "название объединения", True, 1000), "description": "Объединено вручную. Корень — корень первого исследования. Все отношения и исходные интерпретации сохранены.", "rootId": node_map[left["rootId"]], "nodes": nodes, "edges": edges, "archived": False, "createdAt": now(), "merge": {"sourceStudyIds": [left["id"], right["id"]], "matchIds": selected, "nodeMap": node_map, "decisions": [copy.deepcopy(m) for m in state["matches"] if m["id"] in selected]}}
        for key, target_key in (("designations", "target"), ("substitutions", "targetId")):
            copies = []
            for s in (left, right):
                for item in s.get(key, []):
                    clone = {**copy.deepcopy(item), "id": uid(), "sourceStudyId": s["id"], "sourceRecordId": item["id"]}
                    clone[target_key] = node_map.get(item[target_key], item[target_key])
                    if key == "substitutions":
                        clone.setdefault("sourceTargetId", item["targetId"])
                        clone["status"] = "archived"
                    else:
                        clone.setdefault("origins", []).append({"studyId": s["id"], "snapshot": copy.deepcopy(item)})
                    copies.append(clone)
            if copies:
                merged[key] = copies
        state["studies"].append(merged)
        return {"studyId": merged["id"], "nodeId": merged["rootId"]}, f"Создано объединение «{merged['title']}»; исходные исследования сохранены"
