"""K003r: check recoverable record and review coverage, not semantic truth."""
import argparse
import hashlib
import json
import platform
import re
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

from app.exchange import graph_export, parse_document
from app.journal import expand_history
from app.store import Store, validate
from scripts.verify_nut import accept, act

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/experiments/nut"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify(graph):
    document, audit = load(graph), load(graph.parent / "revision-audit.json")
    old_bytes = (DATA / "nut.json").read_bytes()
    old = json.loads(old_bytes)["state"]["studies"][0]
    inventory = load(DATA / "revision-inventory.json")
    study = document["state"]["studies"][0]
    nodes, edges = study["nodes"], study["edges"]
    names = {n["label"]: n["id"] for n in nodes}
    pairs = {(e["from"], e["to"]) for e in edges}
    checks = []

    def check(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        assert condition, name

    validate(document["state"])
    parse_document(document)
    check("Original K003 remains byte-identical historical evidence", hashlib.sha256(old_bytes).hexdigest() == audit["originalSha256"] == "f1af2df1882cff05352ca1d0230f04adf60c71a3d7084ad0338c18ec39344600")
    check("New independent study and all new object IDs", study["id"] != old["id"] and not {n["id"] for n in old["nodes"]}.intersection(n["id"] for n in nodes) and not {e["id"] for e in old["edges"]}.intersection(e["id"] for e in edges))
    check("45 concepts / no alpha / 45 edges; no automatic identities", audit["counts"] == {"concepts": 45, "alpha": 0, "edges": 45} and len(nodes) == len(names) == 45 and len(edges) == len(pairs) == 45 and all(n.get("structure", "concept") == "concept" for n in nodes) and not document["state"]["matches"] and not study.get("accumulation"))
    check("Single-word spelling; nominative noun judgment is recorded separately", all(re.fullmatch(r"[а-яё]+", n["label"]) for n in nodes) and "вручную" in audit["semanticReview"]["grammar"])
    check("No semantic descriptions hidden in node fields", all(n["notes"] == n["alternatives"] == n["kind"] == "" for n in nodes))
    check("No semantic descriptions hidden in edge fields", all(e["notes"] == e["type"] == e["componentRole"] == "" and e["role"] == "relation" for e in edges))
    check("Vocabulary does not hide old multiword entries", len(study["designations"]) == 1 and study["designations"][0]["text"] == "гайка" and study["designations"][0]["target"] == study["rootId"] and not study["designations"][0]["notes"])
    check("Audit route addresses exactly match the graph", names == audit["nodeIds"] and pairs == {(names[a], names[b]) for a, b in audit["routes"]})
    reachable = {study["rootId"]}
    for _ in nodes:
        reachable.update(e["to"] for e in edges if e["from"] in reachable)
    check("Every conceptual entry reachable from the root", reachable == set(names.values()))
    indegree = Counter(e["to"] for e in edges)
    check("Only contact has two incoming references; no duplicate context-specific concepts", indegree[names["контакт"]] == 2 and {n for n, count in indegree.items() if count > 1} == {names["контакт"]} and (names["резьба"], names["контакт"]) in pairs and (names["опора"], names["контакт"]) in pairs and (names["контакт"], names["трение"]) in pairs)
    check("Four basic characteristics independently retained", {r["concept"] for r in audit["basicApplicability"]} == {"масса", "форма", "цвет", "материал"} and all((study["rootId"], names[r["concept"]]) in pairs and r["status"] == "applicable" for r in audit["basicApplicability"]))
    check("Every initial candidate and every original node critically reviewed", {r["key"] for r in inventory["candidates"]} == {r["key"] for r in audit["inventoryDecisions"]} and {n["id"] for n in old["nodes"]} == {r["originalId"] for r in audit["originalNodeReview"]} and all(r["limitationOrDecision"] for r in audit["originalNodeReview"]))
    for r in audit["originalNodeReview"]:
        for path in r["paths"]:
            assert all((names[a], names[b]) in pairs for a, b in zip(path, path[1:])), r
    check("Every claimed reconstructed route actually exists", True)
    review = {r["originalLabel"]: r for r in audit["originalNodeReview"]}
    check("Unrepresented diameter roles, engagement and anti-loosening not falsely collapsed", all(review[label]["status"] == "limited" and not review[label]["paths"] for label in ["средний диаметр резьбы", "номинальный диаметр резьбы", "длина резьбового зацепления", "сопротивление самоотвинчиванию"]) and "диаметр" not in names)
    check("Partial reinterpretations / rejected compositions explicitly distinguished", review["сопротивление коррозии"]["status"] == "partial" and review["сопротивление износу"]["status"] == "partial" and len(audit["rejectedCompositions"]) == 3 and audit["originalRejectedByOperator"])
    rows = list(expand_history(document))
    for row in rows:
        validate(row["state"])
    check("History reconstructs the exact final study", rows[-1]["state"] == document["state"] and rows[-1]["id"] == audit["revision"])
    parent = ROOT / "local-data/nut-k003-revision/verification"
    parent.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="roundtrip-", dir=parent))
    assert run.resolve().is_relative_to(parent)
    store = Store(run / "first.sqlite3")
    staged = act(store, "import", document=document)
    check("Import does not accept proposed content before review", not staged["state"]["studies"] and staged["result"]["added"] == 92)
    pending = [p["id"] for p in staged["state"]["proposals"] if p["status"] == "pending"]
    act(store, "review_proposals", decision="accept", proposalIds=pending)
    check("Imported graph and export preserve all fields / IDs exactly", store.read()["state"]["studies"][0] == study and graph_export(store, study["id"])["state"]["studies"][0] == study)
    second = Store(run / "second.sqlite3")
    accept(second, graph_export(store, study["id"]))
    check("Re-export imports exactly into another clean database", second.read()["state"]["studies"][0] == study)
    repeated = act(store, "import", document=document)
    check("Repeated import: no new proposals or duplicate concepts", repeated["result"]["added"] == 0 and store.read()["state"]["studies"][0] == study)
    before = store.read()
    root = next(n for n in nodes if n["id"] == study["rootId"])
    act(store, "edit_node", studyId=study["id"], nodeId=root["id"], label="проба", kind="", notes="", alternatives="", source=root["source"])
    act(store, "restore", targetRevision=before["revision"])
    check("Restore and new Store recover exact pre-edit state", Store(run / "first.sqlite3").read()["state"] == before["state"])
    nonempty = Store(run / "nonempty.sqlite3")
    accept(nonempty, load(DATA / "nut.json"))
    accept(nonempty, load(ROOT / "data/experiments/accumulation/k001-k002-workspace.json"))
    baseline = nonempty.read()["state"]["studies"]
    accept(nonempty, document)
    current = nonempty.read()["state"]
    check("Original K003 and existing two-source canvas remain exact after separate revised import", len(current["studies"]) == len(baseline)+1 and all(s in current["studies"] for s in baseline) and next(s for s in current["studies"] if s["id"] == study["id"]) == study and all(len(s["accumulation"]["sources"]) == 2 for s in current["studies"] if s.get("accumulation")) and not current["matches"])
    return {"scope": "Техническая согласованность записи / покрытия ручного review. Не автоматическое доказательство семантики или принятие оператором.", "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.platform()}, "graph": {"file": str(graph), "sha256": hashlib.sha256(graph.read_bytes()).hexdigest(), "studyId": study["id"], "revision": audit["revision"], **audit["counts"]}, "review": dict(Counter(r["status"] for r in audit["originalNodeReview"])), "checks": checks, "passed": len(checks), "isolatedRun": str(run)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DATA / "nut-revised.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.graph)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"passed": result["passed"], "graph": result["graph"], "review": result["review"]}, ensure_ascii=False))
