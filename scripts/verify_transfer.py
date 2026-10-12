"""K002: конечная проверка маршрутов, записи, независимости и границ ролей.

Лексические / смысловые различия здесь — требования ручного предложения,
не автоматически доказанная семантика.
"""
import argparse
import copy
import hashlib
import json
import platform
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from app.exchange import graph_export, parse_document
from app.journal import expand_history
from app.store import Store, validate
from scripts.transfer_decomposition import COMBINATIONS, ROLE_CANDIDATES, EXECUTION_CANDIDATES, act, write

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/experiments/transfer"
EVIDENCE = ROOT / "docs/manual/evidence/transfer"
STONE = ROOT / "data/experiments/stone/stone.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def accept(store, doc):
    act(store, "import", document=doc)
    pending = [p["id"] for p in store.read()["state"]["proposals"] if p["status"] == "pending"]
    if pending:
        act(store, "review_proposals", decision="accept", proposalIds=pending)
    return pending


def verify():
    doc, flat, audit, relevance = (load(DATA / p) for p in ("transfer.json", "ungrouped.json", "structure-audit.json", "relevance.json"))
    inventory = load(DATA / "inventory.json")["elements"]
    study = doc["state"]["studies"][0]
    sid, root = study["id"], study["rootId"]
    nodes = {n["id"]: n for n in study["nodes"]}
    concepts = [n for n in nodes.values() if n.get("structure", "concept") == "concept"]
    combos = [n for n in nodes.values() if n.get("structure") == "combination"]
    edges = study["edges"]
    checks = []
    def check(name, value, detail=None):
        checks.append({"name": name, "passed": bool(value), "detail": detail})
        if not value:
            raise AssertionError(name)
    validate(doc["state"])
    parse_document(doc)
    check("Самостоятельный JSON v2 study", doc["version"] == 2 and doc["kind"] == "study" and len(doc["state"]["studies"]) == 1)
    check("Первичный сбор до группировки сохранён", not flat["state"]["studies"][0]["edges"] and len(inventory) == 84)
    relevant = relevance["candidates"]
    check("Релевантность всех 84 проверена до группировки", len(relevant) == 84 and {r["label"] for r in relevant} == {r["label"] for r in inventory}
          and all(r["status"] and r["reason"] for r in relevant) and relevance["sourceRevision"] == audit["sourceRevision"])
    check("Первичные ID сохранены или восстановлены", all(n["id"] == audit["conceptIds"][n["label"]] for n in flat["state"]["studies"][0]["nodes"] if n["label"] in audit["conceptIds"]))
    check("Исход каждого кандидата записан", {n["label"] for n in concepts} | {r["label"] for r in audit["excludedCandidates"]}
          == {r["label"] for r in inventory} | {"передача", "нормативность", "преемственность", "пас"})
    labels = {n["label"] for n in concepts}
    check("Нет схем участников и выполнения в актуальном графе", not labels & (ROLE_CANDIDATES | EXECUTION_CANDIDATES | {"изменение"}), sorted(labels))
    check("Устройство и пас не раскрываются функционально", all(not any(e["from"] == audit["conceptIds"][label] for e in edges) for label in ("механизм", "пас")))
    check("Концепты однословные, α анонимны, категории не навязаны", all(re.fullmatch(r"[а-яё]+", n["label"]) for n in concepts)
          and all(not n["label"] for n in combos) and all(not n["kind"] for n in nodes.values()) and not {"процесс", "действие"} & labels)
    check("Две концептуальные α, без распределения ролей", len(combos) == 2 and {e.get("componentRole") for e in edges if e.get("role") == "component"}
          == {"смысловая грань", "выразительная грань", "энергетическая область", "кинематическая область"})
    check("Один лексический вход, без прямых дублей", all(e["type"] == "чтение" for e in edges if e["from"] == root)
          and len({(e["from"], e["to"]) for e in edges}) == len(edges) and len(audit["functions"]) == len(edges))
    outgoing = defaultdict(list)
    for e in edges:
        outgoing[e["from"]].append(e["to"])
    def paths(start):
        found = defaultdict(list)
        def walk(node, route):
            if node in route:
                raise AssertionError("Цикл")
            route = route + [node]
            found[node].append(route)
            for target in outgoing[node]:
                walk(target, route)
        walk(start, [])
        return found
    def node_id(key):
        return audit["combinationIds"][key[1:]] if key.startswith("@") else audit["conceptIds"][key]
    per_reading = {r["code"]: paths(node_id(r["key"])) for r in audit["readings"]}
    check("Ровно один маршрут внутри каждого чтения", len(per_reading) == 11 and all(len(route) == 1 for found in per_reading.values() for route in found.values()))
    check("Все актуальные узлы связаны", {root} | {n for found in per_reading.values() for n in found} == set(nodes))
    shared = audit["combinationIds"]["representation"]
    check("Содержание / форма переиспользуется через α", len([e for e in edges if e["to"] == shared]) == 3
          and all(outgoing[audit["conceptIds"][k]].count(shared) == 1 for k in ("сообщение", "воспроизведение", "программа"))
          and not any(e["from"] in {audit["conceptIds"][k] for k in ("сообщение", "воспроизведение", "программа")}
                      and e["to"] in {audit["conceptIds"][k] for k in ("содержание", "форма")} for e in edges))
    check("Общее слово не отождествляет чтения", len([d for d in study["designations"] if d["text"] == "передача"]) == 11
          and not study.get("substitutions") and not doc["state"]["matches"])
    check("Нет значений экземпляров в данных", all(set(n) <= {"id", "label", "kind", "notes", "alternatives", "source", "origins", "createdAt", "structure", "x", "y"} for n in nodes.values())
          and all(not n["kind"] for n in nodes.values()))
    snapshots = {h["id"]: h["state"] for h in expand_history(doc)}
    check("Первичный / отвергнутый / итоговый этапы восстанавливаются", snapshots[86]["studies"][0] == flat["state"]["studies"][0]
          and snapshots[274]["studies"][0] == load(EVIDENCE / "role-trial.json")["state"]["studies"][0]
          and snapshots[audit.get("dataRevision", audit["targetRevision"])]["studies"][0] == study)
    observations = []
    contrasts = [
        ("R01", "R02", "Пространственная и нормативная грани различены; переход отношений не моделируется", "перемещение", "право"),
        ("R03", "R06", "Сообщение и выразительное воспроизведение различены при общей структуре представления", "достоверность", "точность"),
        ("R04", "R07", "Физическая смысловая область и лексическое устройство различены без конструкции выполнения", "энергия", "механизм"),
        ("R07", "R08", "Устройство и постоянный концепт режима различены, переключение отсутствует", "механизм", "состояние"),
        ("R03", "R09", "Сообщение и организованный выпуск различены без адресата / аудитории", "достоверность", "последовательность"),
        ("R01", "R10", "Перемещение и материальный пакет различены без акта вручения", "перемещение", "упаковка"),
    ]
    leaves = {key: {nodes[n]["label"] for n in found if nodes[n].get("structure", "concept") == "concept"} for key, found in per_reading.items()}
    for a, b, requirement, ma, mb in contrasts:
        recorded = ma in leaves[a] and ma not in leaves[b] and mb in leaves[b] and mb not in leaves[a]
        check(f"Раздельная постоянная запись: {a} / {b}", recorded)
        observations.append({"a": a, "b": b, "requirement": requirement, "recorded": recorded, "semanticProof": False})
    temp_parent = ROOT / "local-data/transfer-k002/verification"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_parent) as temp:
        db = Path(temp) / "roundtrip.sqlite3"
        store = Store(db)
        act(store, "import", document=doc)
        pending = [p["id"] for p in store.read()["state"]["proposals"] if p["status"] == "pending"]
        check("Импорт сначала очередь кандидатов", not store.read()["state"]["studies"] and bool(pending))
        act(store, "review_proposals", decision="accept", proposalIds=pending)
        check("Полный обмен сохраняет запись и ID", store.read()["state"]["studies"][0] == study and graph_export(store, sid)["state"]["studies"][0] == study)
        act(store, "import", document=doc)
        check("Повторный импорт не дублирует", not [p for p in store.read()["state"]["proposals"] if p["status"] == "pending"] and store.read()["state"]["studies"][0] == study)
        check("Новый Store сохраняет доступ к графу", Store(db).read()["state"]["studies"][0] == study)
        fragment = graph_export(store, sid, shared, 1)
        fresh = Store(Path(temp) / "fragment.sqlite3")
        accept(fresh, fragment)
        check("Фрагмент переносит α и концептуальные компоненты", fresh.read()["state"]["studies"][0] == fragment["state"]["studies"][0]
              and {audit["conceptIds"][k] for k in ("содержание", "форма")} <= {n["id"] for n in fragment["state"]["studies"][0]["nodes"]})
        stone = load(STONE)["state"]["studies"][0]
        accept(store, load(STONE))
        state = store.read()["state"]
        check("K001 и K002 независимы", len(state["studies"]) == 2 and not state["matches"]
              and next(s for s in state["studies"] if s["id"] == stone["id"]) == stone and not {n["id"] for n in stone["nodes"]} & set(nodes))
    stone_labels = {n["id"]: n["label"] for n in stone["nodes"]}
    stone_out = defaultdict(list)
    for e in stone["edges"]:
        stone_out[e["from"]].append(e["to"])
    def stone_path(label):
        def walk(n, route):
            if stone_labels[n] == label:
                return route + [label]
            for t in stone_out[n]:
                result = walk(t, route + [stone_labels[n]])
                if result:
                    return result
        return walk(stone["rootId"], [])
    overlaps = sorted(labels & set(stone_labels.values()))
    comparison = []
    for label in overlaps:
        nid = audit["conceptIds"][label]
        comparison.append({"label": label, "k001Id": next(n["id"] for n in stone["nodes"] if n["label"] == label), "k002Id": nid,
            "k001Path": stone_path(label), "k002Paths": [{"reading": key, "path": [next(("@"+k for k,v in audit["combinationIds"].items() if v == n), nodes[n]["label"]) for n in found[nid][0]]} for key, found in per_reading.items() if nid in found],
            "decision": "Не отождествлено; требуется человеческое семантическое сравнение области и функции"})
    write(DATA / "comparison-k001.json", {"baseline": {"file": "data/experiments/stone/stone.json", "sha256": hashlib.sha256(STONE.read_bytes()).hexdigest()},
        "scope": "После K002.2r; только сравнение постоянных концептов, без matches / merge", "sameLabels": comparison,
        "excludedOnly": sorted(({r["label"] for r in inventory} & set(stone_labels.values())) - labels),
        "counts": {"K001": {"concepts": len(stone["nodes"]), "combinations": 0, "edges": len(stone["edges"])}, "K002": {"concepts": len(concepts), "combinations": len(combos), "edges": len(edges)}}})
    write(EVIDENCE / "contrasts.json", {"stage": "K002.2r", "scope": "Различия постоянной записи, не доказанная семантика", "contrasts": observations,
        "limitations": ["Реляционное ядро передавания требует участников и отношений; раскрытие остановлено по границе задачи.",
                        "Функциональная конструкция устройства и спортивного паса не исследуются.",
                        "α объединяет смысловые грани; редактор не исполняет обязательность, альтернативность или логическую конъюнкцию.",
                        "Общность содержания / формы и преемственности — ручные гипотезы, не установленные универсальные определения."]})
    result = {"scope": "Структурные требования и сохранность K002.2r; смысловая истинность не проверена", "sourceCode": "M004 8ae2b13; app/ не изменён",
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version},
        "graph": {"file": "data/experiments/transfer/transfer.json", "sha256": hashlib.sha256((DATA / "transfer.json").read_bytes()).hexdigest(), "studyId": sid, "rootId": root,
                  "concepts": len(concepts), "combinations": len(combos), "edges": len(edges), "designations": len(study["designations"]), "revision": audit.get("dataRevision", audit["targetRevision"])},
        "perReadingPaths": {key: len(found) for key, found in per_reading.items()}, "checks": checks, "passed": len(checks)}
    write(EVIDENCE / "verification.json", result)
    print(f"K002.2r: {len(checks)} проверок; {len(concepts)} концептов + {len(combos)} α / {len(edges)} рёбер; повторения {overlaps}")


if __name__ == "__main__":
    verify()
