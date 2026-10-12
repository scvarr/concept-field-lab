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
from scripts.transfer_decomposition import COMBINATIONS, SENSES, act, write

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
    doc, flat, audit = (load(DATA / p) for p in ("transfer.json", "ungrouped.json", "structure-audit.json"))
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
    check("Первичный сбор до группировки", not flat["state"]["studies"][0]["edges"] and len(inventory) == 84
          and all(n.get("structure", "concept") == "concept" for n in flat["state"]["studies"][0]["nodes"]))
    check("Идентичность первичных концептов сохранена", all(n["id"] in nodes for n in flat["state"]["studies"][0]["nodes"]
          if n["label"] in audit["conceptIds"]))
    check("Каждый кандидат имеет исход или причину отказа", {n["label"] for n in concepts}
          | {n["label"] for n in audit["excludedCandidates"]} == {n["label"] for n in inventory} | {"передача", "изменение"}
          and all(n["reason"] for n in audit["excludedCandidates"]))
    check("Концепты однословные, α анонимны, род не назначен", all(re.fullmatch(r"[а-яё]+", n["label"]) for n in concepts)
          and all(not n["label"] for n in combos) and all(not n["kind"] for n in nodes.values())
          and not {"процесс", "действие"} & {n["label"] for n in concepts})
    root_edges = [e for e in edges if e["from"] == root]
    component_edges = [e for e in edges if e.get("role") == "component"]
    check("Корень только различает чтения", len(root_edges) == 13 and all(e["type"] == "чтение" and e["to"] in audit["combinationIds"].values() for e in root_edges)
          and len(component_edges) + len(root_edges) == len(edges))
    check("Включения имеют одну объяснённую функцию", all(e["componentRole"] and e["notes"] and not e["type"] for e in component_edges)
          and len(audit["inclusions"]) == len(component_edges))
    check("Нет параллельных дублей и возврата к корню", len({(e["from"], e["to"]) for e in edges}) == len(edges)
          and all(e["to"] != root for e in edges))
    outgoing = defaultdict(list)
    for e in component_edges:
        outgoing[e["from"]].append(e)

    def paths(start):
        found = defaultdict(list)
        def walk(node, path):
            if node in path:
                raise AssertionError("Цикл состава")
            path = path + [node]
            found[node].append(path)
            for edge in outgoing[node]:
                walk(edge["to"], path)
        walk(start, [])
        return found

    per_sense = {key: paths(audit["combinationIds"][key]) for key in SENSES}
    check("Один маршрут к каждой позиции внутри чтения", all(len(routes) == 1 for found in per_sense.values() for routes in found.values()))
    reachable = {root} | {n for found in per_sense.values() for n in found}
    check("Все итоговые элементы имеют маршрут", reachable == set(nodes) and all(outgoing[n["id"]] for n in combos))
    check("Переиспользование α без обходов компонентов", sum(1 for e in component_edges if e["to"] == audit["combinationIds"]["direction"]) == 5
          and audit["combinationIds"]["physical"] in per_sense["mechanism"]
          and not any(e["from"] == audit["combinationIds"]["mechanism"] and e["to"] in {
              audit["conceptIds"]["энергия"], audit["conceptIds"]["источник"]} for e in edges))
    check("Слово адресует раздельные чтения без замещения", len([d for d in study["designations"] if d["text"] == "передача"]) == 13
          and not study.get("substitutions") and not doc["state"]["matches"])
    check("Нет значений экземпляров в полях модели", all(set(n) <= {"id", "label", "kind", "notes", "alternatives", "source", "origins", "createdAt", "structure", "x", "y"} for n in nodes.values())
          and all("экземпляр" not in n["kind"] for n in nodes.values()))
    snapshots = {h["id"]: h["state"] for h in expand_history(doc)}
    check("Оба этапа восстанавливаются из истории", snapshots[86]["studies"][0] == flat["state"]["studies"][0]
          and snapshots[audit["targetRevision"]]["studies"][0] == study)

    # Конечные требования к различению чтений; наблюдаем только раздельные
    # составы, без заявления, что множество листьев исполняет этот смысл.
    contrasts = [
        ("item", "rights", "Вручение вещи не гарантирует смену собственника", "вещь", "право"),
        ("information", "item", "Копирование сообщения не обязано лишать источник содержания", "сообщение", "тождество"),
        ("information", "rendering", "Перенос сигнала и выражение содержания — разные позиции", "сигнал", "форма"),
        ("physical", "mechanism", "Физическая функция и выполняющее её устройство различены", "энергия", "механизм"),
        ("mechanism", "gear", "Устройство и выбор режима не отождествлены", "вращение", "переключение"),
        ("information", "broadcast", "Сообщение и выпуск вещания различены", "кодирование", "программа"),
        ("item", "parcel", "Акт вручения и передаваемый пакет различены", "доставка", "упаковка"),
        ("agent", "heredity", "Материальный фактор и воспроизведение признака различены", "агент", "наследственность"),
        ("heredity", "culture", "Биологическое и культурное воспроизведение различены", "наследственность", "обучение"),
        ("pass", "item", "Спортивный пас имеет собственную область участников", "игрок", "тождество"),
    ]
    leaves = {key: {nodes[n]["label"] for n in found if nodes[n].get("structure", "concept") == "concept"} for key, found in per_sense.items()}
    observations = []
    for a, b, requirement, marker_a, marker_b in contrasts:
        ok = marker_a in leaves[a] and marker_a not in leaves[b] and marker_b in leaves[b]
        # Устройство намеренно повторно использует физическую функцию.
        if a == "physical" and b == "mechanism":
            ok = marker_a in leaves[a] and marker_a in leaves[b] and marker_b not in leaves[a] and marker_b in leaves[b]
        check(f"Раздельная запись: {a} / {b}", ok)
        observations.append({"a": a, "b": b, "requirement": requirement,
                             "recorded": ok, "semanticProof": False})

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    temp_parent = ROOT / "local-data/transfer-k002/verification"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_parent) as temp:
        db = Path(temp) / "roundtrip.sqlite3"
        store = Store(db)
        act(store, "import", document=doc)
        check("Импорт сначала создаёт очередь", not store.read()["state"]["studies"] and bool(store.read()["state"]["proposals"]))
        act(store, "review_proposals", decision="accept", proposalIds=[p["id"] for p in store.read()["state"]["proposals"] if p["status"] == "pending"])
        check("Полный обмен сохраняет структуру и ID", store.read()["state"]["studies"][0] == study and graph_export(store, sid)["state"]["studies"][0] == study)
        act(store, "import", document=doc)
        check("Повторный импорт без дублей", not [p for p in store.read()["state"]["proposals"] if p["status"] == "pending"] and store.read()["state"]["studies"][0] == study)
        check("Новый объект Store продолжает запись", Store(db).read()["state"]["studies"][0] == study)
        alpha = audit["combinationIds"]["direction"]
        fragment = graph_export(store, sid, alpha, 1)
        fresh = Store(Path(temp) / "fragment.sqlite3")
        accept(fresh, fragment)
        check("Фрагмент α переносит компоненты и роли", fresh.read()["state"]["studies"][0] == fragment["state"]["studies"][0]
              and all(audit["conceptIds"][k] in {n["id"] for n in fragment["state"]["studies"][0]["nodes"]} for k in ("источник", "приёмник", "направленность")))
        stone = load(STONE)["state"]["studies"][0]
        accept(store, load(STONE))
        state = store.read()["state"]
        check("K001 / K002 сосуществуют независимо", len(state["studies"]) == 2 and not state["matches"]
              and next(s for s in state["studies"] if s["id"] == stone["id"]) == stone
              and not {n["id"] for n in stone["nodes"]} & set(nodes))
        # Без конкретных участников: меняем только абстрактную подпись роли.
        edge = copy.deepcopy(next(e for e in component_edges if e["from"] == alpha and e["to"] == audit["conceptIds"]["источник"]))
        act(store, "edit_edge", studyId=sid, edgeId=edge["id"], **{k: v for k, v in edge.items() if k not in ("id", "origins")},)
        payload = {k: v for k, v in edge.items() if k not in ("id", "origins")}
        payload["componentRole"] = "произвольная роль без связывания"
        act(store, "edit_edge", studyId=sid, edgeId=edge["id"], **payload)
        recorded = next(s for s in Store(db).read()["state"]["studies"] if s["id"] == sid)
        check("Отрицательная проба: роль — свободная строка", next(e for e in recorded["edges"] if e["id"] == edge["id"])["componentRole"] == payload["componentRole"])
        check("Проба не меняет K001", next(s for s in store.read()["state"]["studies"] if s["id"] == stone["id"]) == stone)

    overlaps = sorted({n["label"] for n in concepts} & {n["label"] for n in stone["nodes"]})
    comparison = []
    stone_out = defaultdict(list)
    for e in stone["edges"]:
        stone_out[e["from"]].append(e["to"])
    stone_labels = {n["id"]: n["label"] for n in stone["nodes"]}
    def stone_path(label):
        def walk(node, route):
            if stone_labels[node] == label:
                return route + [label]
            for target in stone_out[node]:
                found = walk(target, route + [stone_labels[node]])
                if found:
                    return found
        return walk(stone["rootId"], [])
    for label in overlaps:
        tid = audit["conceptIds"][label]
        comparison.append({"label": label, "k001Id": next(n["id"] for n in stone["nodes"] if n["label"] == label),
                           "k002Id": tid, "k001Path": stone_path(label),
                           "k002Paths": [{"sense": key, "path": [next((k for k, v in audit["combinationIds"].items() if v == n), nodes[n]["label"]) for n in routes[0]]}
                                         for key, found in per_sense.items() if (routes := found.get(tid))],
                           "decision": "Не отождествлено; отдельный человеческий review функций и области"})
    write(DATA / "comparison-k001.json", {
        "baseline": {"file": "data/experiments/stone/stone.json", "sha256": hashlib.sha256(STONE.read_bytes()).hexdigest()},
        "scope": "Сравнение после построения K002, без matches / merge / замещения", "sameLabels": comparison,
        "excludedOnly": sorted({n["label"] for n in inventory} & set(stone_labels.values()) - set(overlaps)),
        "counts": {"K001": {"concepts": len(stone["nodes"]), "combinations": 0, "edges": len(stone["edges"])},
                   "K002": {"concepts": len(concepts), "combinations": len(combos), "edges": len(edges)}}})
    write(EVIDENCE / "contrasts.json", {"scope": "Требования и наблюдаемые различия записи, не независимая семантическая оценка", "contrasts": observations,
        "limitations": [{"requirement": "Связать источник, приёмник и переносимое в одном отношении", "status": "Сохраняются именованные позиции; связывания аргументов / переменных нет"},
                        {"requirement": "Задать один предмет и разные стороны до / после", "status": "Нет исполняемых ограничений тождества, стадий и состояния"},
                        {"requirement": "Различить обязательное, возможное и альтернативное", "status": "componentRole / notes — строки; состав не исполняет кванторы / условие / дизъюнкцию"}]})
    result = {"scope": "Сохранность и структурные требования K002; смысловая истинность не проверена",
              "sourceCode": "M004 8ae2b13; app/ не изменён", "environment": {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version},
              "graph": {"file": "data/experiments/transfer/transfer.json", "sha256": hashlib.sha256((DATA / "transfer.json").read_bytes()).hexdigest(),
                        "studyId": sid, "rootId": root, "concepts": len(concepts), "combinations": len(combos), "edges": len(edges), "designations": len(study["designations"])},
              "perSensePaths": {key: len(found) for key, found in per_sense.items()}, "checks": checks, "passed": len(checks)}
    write(EVIDENCE / "verification.json", result)
    print(f"K002: {len(checks)} проверок прошли; {len(concepts)} концептов + {len(combos)} α / {len(edges)} рёбер; сравнение {overlaps}")


if __name__ == "__main__":
    verify()
