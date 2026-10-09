"""Finite 5000-node exchange/persistence benchmark; writes local evidence."""
import json
import platform
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from app.exchange import graph_export, neighbourhood
from app.store import Store
from scripts.fixtures import large


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "test-output"
    output.mkdir(exist_ok=True)
    timings = {}

    def timed(name, fn):
        start = perf_counter()
        result = fn()
        timings[name] = round(perf_counter() - start, 4)
        return result

    doc = large()
    (output / "large-graph.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="scale-", dir=output) as directory:
        store = Store(Path(directory) / "workspace.sqlite3")
        staged = timed("stage_15001_candidates", lambda: store.mutate("import", {"document": doc}, 0))
        assert staged["result"]["added"] == 15001
        ids = [p["id"] for p in staged["state"]["proposals"]]
        applied = timed("accept_15001_candidates", lambda: store.mutate("review_proposals", {"proposalIds": ids, "decision": "accept"}, 1))
        study = applied["state"]["studies"][0]
        assert len(study["nodes"]) == 5000 and len(study["edges"]) == 10000
        reopened = timed("reopen_and_read", lambda: Store(store.path).read())
        assert reopened["state"] == applied["state"]
        fragment = timed("depth_3_export_with_history", lambda: graph_export(store, study["id"], study["rootId"], 3))
        assert len(fragment["state"]["studies"][0]["nodes"]) < 100
        assert len(neighbourhood(study, study["rootId"], None)) == 5000
        complete = timed("complete_study_export", lambda: graph_export(store, study["id"]))
        assert len(complete["state"]["studies"][0]["nodes"]) == 5000
        repeated = timed("repeat_import_no_duplicates", lambda: store.mutate("import", {"document": doc}, 2))
        assert repeated["result"]["added"] == 0
        assert len(repeated["state"]["studies"][0]["nodes"]) == 5000
        edit = {**study["nodes"][0], "notes": "Редактирование крупного графа"}
        timed("single_node_edit", lambda: store.mutate("edit_node", {"studyId": study["id"], "nodeId": edit["id"], **edit}, 3))
        assert store.read()["state"]["studies"][0]["nodes"][0]["notes"] == edit["notes"]
        def twenty_edits():
            for i in range(20):
                store.mutate("edit_node", {"studyId": study["id"], "nodeId": edit["id"], **edit, "notes": f"Сохранённая версия {i}"}, 4 + i)
        timed("twenty_sequential_edits", twenty_edits)
        backup = timed("full_workspace_export_after_20_edits", store.export)
        backup_bytes = len(json.dumps(backup, ensure_ascii=False).encode("utf-8"))
        assert backup_bytes < 64 * 1024 * 1024, backup_bytes
        def validate_history():
            store.parse_import(backup)
        timed("validate_full_backup_and_all_versions", validate_history)
        assert all(value < 30 for value in timings.values()), timings
        result = {"result": "passed", "python": sys.version, "os": platform.platform(), "nodes": 5000, "edges": 10000, "timings_seconds": timings, "database_bytes": store.path.stat().st_size, "backup_after_20_edits_bytes": backup_bytes, "fixture_json_bytes": (output / "large-graph.json").stat().st_size, "criterion": "Each operation <30 seconds; exact IDs, counts, persistent state, no duplicates; compact backup <64 MiB after 20 edits, all versions validated; no semantic claim"}
    (output / "scale-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
