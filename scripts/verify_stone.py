"""Предметная проверка K001: правила записи, история и обмен, не семантика."""
import argparse
import hashlib
import json
import platform
import re
import sqlite3
import tempfile
from collections import Counter, deque
from pathlib import Path

from app.exchange import graph_export, parse_document
from app.journal import expand_history
from app.store import Store, validate


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify(graph, baseline, audit):
    document = load(graph)
    before = load(baseline)["state"]["studies"][0]
    changes = load(audit)
    checks = []

    def check(name, condition, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(name)

    validate(document["state"])
    parse_document(document)
    study = document["state"]["studies"][0]
    check("JSON v2 одного исследования", document["version"] == 2 and document["kind"] == "study"
          and len(document["state"]["studies"]) == 1)
    nodes, edges = study["nodes"], study["edges"]
    labels = {n["id"]: n["label"] for n in nodes}
    by_label = {n["label"]: n["id"] for n in nodes}
    check("Однословные имена без значений", all(re.fullmatch(r"[а-яё]+", n["label"]) for n in nodes)
          and len(by_label) == len(nodes), list(by_label))
    check("Нет скрытых определений или структур вне границы", all(
        n.get("structure", "concept") == "concept" and not n["kind"] and not n["notes"] for n in nodes)
          and all(not e["notes"] for e in edges) and not study.get("designations")
          and not study.get("substitutions") and not document["state"]["matches"])
    check("Один выбранный тип раскрытия", all(e.get("role", "relation") == "relation"
          and e["type"] == "аспект" for e in edges))
    root = study["rootId"]
    check("Сохранена идентичность корня", root == before["rootId"] and labels[root] == "камень")
    old_ids = {n["label"]: n["id"] for n in before["nodes"]}
    check("Существующие концепты не дублированы", all(by_label[k] == v for k, v in old_ids.items()
          if k in by_label))
    adjacency = {n["id"]: [] for n in nodes}
    incoming = Counter(e["to"] for e in edges)
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
    check("Нет параллельных рёбер", len({(e["from"], e["to"]) for e in edges}) == len(edges))
    check("Ровно один вход к каждой позиции", not incoming[root] and all(incoming[n["id"]] == 1
          for n in nodes if n["id"] != root))
    paths = {root: [root]}
    queue = deque([root])
    cycle = False
    while queue:
        a = queue.popleft()
        for b in adjacency[a]:
            if b in paths:
                cycle = True
                continue
            paths[b] = paths[a] + [b]
            queue.append(b)
    check("Нет циклов, обходных путей и несвязанных элементов", not cycle and len(paths) == len(nodes)
          and len(edges) == len(nodes) - 1, {"nodes": len(nodes), "edges": len(edges)})
    check("Масса только через характеристику", [labels[n] for n in paths[by_label["масса"]]]
          == ["камень", "характеристика", "масса"] and adjacency[root] == [by_label["характеристика"]])
    selected_paths = {k: [labels[n] for n in paths[by_label[k]]] for k in
                      ("объём", "цвет", "плотность", "пористость", "температура", "вещество")}
    check("Позиции имеют разные выбранные области", all(len(v) >= 4 for v in selected_paths.values()), selected_paths)
    check("Удаления и переносы имеют первичный след", all(n["id"] not in labels and n["reason"]
          for n in changes["removedNodes"]) and all(e["id"] in {x["id"] for x in edges}
          and e["reason"] for e in changes["movedEdges"]),
          {k: len(changes[k]) for k in ("removedNodes", "removedEdges", "movedEdges", "addedEdges")})
    history = list(expand_history(document))
    snapshots = {h["id"]: h["state"]["studies"][0] for h in history}
    check("Исходный и прежний варианты восстанавливаются без чата", snapshots[52] == before
          and len(snapshots[182]["nodes"]) == 49 and len(snapshots[182]["edges"]) == 114
          and snapshots[299] == study, {"versions": len(history), "latest": history[-1]["id"]})
    repo = Path(__file__).resolve().parents[1]
    temp_parent = repo / "local-data" / "stone-k001" / "verification"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="roundtrip-", dir=temp_parent) as temp:
        assert Path(temp).resolve().is_relative_to(repo)
        db = Path(temp) / "roundtrip.sqlite3"
        store = Store(db)
        imported = store.mutate("import", {"document": document}, store.read()["revision"])
        pending = [p["id"] for p in imported["state"]["proposals"] if p["status"] == "pending"]
        check("Импорт не принимает граф до review", not imported["state"]["studies"] and len(pending) > 0,
              {"candidates": len(pending)})
        store.mutate("review_proposals", {"decision": "accept", "proposalIds": pending},
                     store.read()["revision"])
        check("Импорт и экспорт сохраняют полный граф и ID", store.read()["state"]["studies"][0] == study
              and graph_export(store, study["id"])["state"]["studies"][0] == study)
        repeated = store.mutate("import", {"document": document}, store.read()["revision"])
        check("Повторный импорт не дублирует данные", repeated["state"]["studies"][0] == study
              and not [p for p in repeated["state"]["proposals"] if p["status"] == "pending"])
        check("Повторное открытие базы сохраняет граф", Store(db).read()["state"]["studies"][0] == study)
        fragment = graph_export(store, study["id"], by_label["материал"], 0)
        check("Фрагмент не приписывает достижимые свойства", len(fragment["state"]["studies"][0]["nodes"]) == 1
              and not fragment["state"]["studies"][0]["edges"])
    return {"scope": "Технические правила записи и обмен. Семантика и элементарность не проверяются.",
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "sqlite": sqlite3.sqlite_version},
            "graph": {"file": graph.as_posix(), "sha256": hashlib.sha256(graph.read_bytes()).hexdigest(),
                      "studyId": study["id"], "rootId": root, "nodes": len(nodes), "edges": len(edges)},
            "checks": checks, "passed": len(checks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=Path("data/experiments/stone/stone.json"))
    parser.add_argument("--baseline", type=Path, default=Path("data/experiments/stone/baseline.json"))
    parser.add_argument("--audit", type=Path, default=Path("docs/manual/evidence/stone/revision-audit.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.graph, args.baseline, args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"K001: {result['passed']} проверок прошли; {result['graph']['nodes']}/{result['graph']['edges']}")


if __name__ == "__main__":
    main()
