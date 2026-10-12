"""K003 record / exchange / recovery checks; no semantic truth test."""
import argparse
import hashlib
import json
import platform
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from app.exchange import graph_export, parse_document
from app.journal import expand_history
from app.store import Store, validate

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def act(store, action, **data):
    return store.mutate(action, data, store.read()["revision"])


def accept(store, doc):
    act(store, "import", document=doc)
    pending = [p["id"] for p in store.read()["state"]["proposals"] if p["status"] == "pending"]
    if pending:
        act(store, "review_proposals", decision="accept", proposalIds=pending, reason="Только изолированная техническая проверка записи K003")


def verify(graph):
    doc = load(graph)
    audit = load(graph.parent / "structure-audit.json")
    inventory = load(ROOT / "data/experiments/nut/inventory.json")
    flat = load(graph.parent / "ungrouped.json")
    validate(doc["state"])
    parse_document(doc)
    study = doc["state"]["studies"][0]
    nodes, edges = study["nodes"], study["edges"]
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        assert condition, name

    check("Standalone v3 study; no automatic accumulation or identity", doc["version"] == 3 and doc["kind"] == "study" and len(doc["state"]["studies"]) == 1 and not study.get("accumulation") and not doc["state"]["matches"])
    check("Full mixed inventory and decision coverage", len(inventory["candidates"]) == 64 and {r["id"] for r in inventory["candidates"]} == {r["id"] for r in audit["decisions"]} and all(r["reason"] for r in audit["decisions"]))
    check("Counts match recorded final result", len(nodes) == 42 and len(edges) == 41 and audit["counts"] == {"concepts": 41, "alpha": 1, "edges": 41})
    ids = {n["id"] for n in nodes}
    check("Audit addresses every final node and edge", set(audit["nodeKeys"].values()) == ids and {e["id"] for e in audit["edges"]} == {e["id"] for e in edges})
    check("All directed edges have valid distinct endpoints and explanations", all(e["from"] in ids and e["to"] in ids and e["from"] != e["to"] and e["notes"] for e in edges))
    reachable = {study["rootId"]}
    for _ in nodes:
        reachable.update(e["to"] for e in edges if e["from"] in reachable)
    check("All nodes reachable by the chosen directed decomposition", reachable == ids)
    check("Single selected route per non-root position", Counter(e["to"] for e in edges) == Counter({nid: 1 for nid in ids - {study["rootId"]}}))
    alpha = next(n for n in nodes if n.get("structure") == "combination")
    components = [e for e in edges if e.get("role") == "component"]
    check("One anonymous alpha with six geometrical components", alpha["label"] == "" and len(components) == 6 and all(e["from"] == alpha["id"] for e in components))
    check("No universal semantic edge classification inserted", all(e["type"] == "" and e.get("role") in ("relation", "component") for e in edges))
    designations = study["designations"]
    check("External vocabulary separate from conceptual nodes", len(designations) == 3 and all(d["target"] in ids for d in designations) and any(d["target"] == alpha["id"] for d in designations))
    check("Ungrouped evidence remains 65/0", len(flat["state"]["studies"][0]["nodes"]) == 65 and not flat["state"]["studies"][0]["edges"])
    history = list(expand_history(doc))
    for row in history:
        validate(row["state"])
    check("Complete history reconstructs the final state", history[-1]["state"] == doc["state"] and history[-1]["id"] == 220)
    check("History retains the pre-grouping snapshot", any(row["state"] == flat["state"] for row in history))
    parent = ROOT / "local-data/nut-k003/verification"
    parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="roundtrip-", dir=parent))
    assert run.resolve().is_relative_to(ROOT / "local-data/nut-k003")
    store = Store(run / "clean.sqlite3")
    staged = act(store, "import", document=doc)
    check("Import only stages before review", not staged["state"]["studies"] and any(p["status"] == "pending" for p in staged["state"]["proposals"]))
    pending = [p["id"] for p in staged["state"]["proposals"] if p["status"] == "pending"]
    act(store, "review_proposals", decision="accept", proposalIds=pending)
    check("Accepted graph and all ID/fields exactly preserved", store.read()["state"]["studies"][0] == study)
    exported = graph_export(store, study["id"])
    check("Export preserves complete study", exported["state"]["studies"][0] == study)
    recovered = Store(run / "second.sqlite3")
    accept(recovered, exported)
    check("Re-export imports into another clean database exactly", recovered.read()["state"]["studies"][0] == study)
    repeated = act(store, "import", document=doc)
    check("Repeated import: no new candidates or graph duplicates", repeated["result"]["added"] == 0 and store.read()["state"]["studies"][0] == study)
    before = store.read()
    root = next(n for n in nodes if n["id"] == study["rootId"])
    act(store, "edit_node", studyId=study["id"], nodeId=root["id"], label="Изолированная проба восстановления", kind=root["kind"], notes=root["notes"], source=root["source"])
    act(store, "restore", targetRevision=before["revision"])
    check("Local history restore exactly recovers pre-edit state", store.read()["state"] == before["state"])
    check("New Store process preserves the graph", Store(run / "clean.sqlite3").read()["state"]["studies"][0] == study)
    nonempty = Store(run / "nonempty.sqlite3")
    canvas_doc = load(ROOT / "data/experiments/accumulation/k001-k002-workspace.json")
    accept(nonempty, canvas_doc)
    old = nonempty.read()["state"]["studies"]
    accept(nonempty, doc)
    current = nonempty.read()["state"]
    check("Import K003 separately preserves existing K001+K002 canvas", all(s in current["studies"] for s in old) and len(current["studies"]) == len(old)+1 and next(s for s in current["studies"] if s["id"] == study["id"]) == study)
    check("No third source appended or semantic matches accepted", all(len(s["accumulation"]["sources"]) == 2 for s in current["studies"] if s.get("accumulation")) and not current["matches"])
    return {"scope": "Техническая запись / обмен / восстановление. Истинность, элементарность и полнота смыслов не проверяются.", "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.platform()}, "graph": {"file": graph.as_posix(), "sha256": hashlib.sha256(graph.read_bytes()).hexdigest(), "studyId": study["id"], "rootId": study["rootId"], **audit["counts"]}, "decisions": dict(Counter(r["status"] for r in audit["decisions"])), "isolatedRun": str(run), "checks": checks, "passed": len(checks)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=ROOT / "data/experiments/nut/nut.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.graph)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"passed": result["passed"], "graph": result["graph"], "decisions": result["decisions"]}, ensure_ascii=False))
