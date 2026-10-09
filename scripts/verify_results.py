"""Independent arithmetic and provenance checks of saved research artifacts."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def same(actual, expected):
    if expected is None:
        assert actual is None
    else:
        assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12), (actual, expected)


def check_set_metrics(xs, model, metric):
    assert len(xs) == metric["n"]
    assert len({x["doc"] for x in xs}) == metric["docs"]
    correct = tp = fp = fn = answered = 0
    for x in xs:
        gold, pred = set(x["gold"]), set(x["models"][model]["prediction"])
        assert x["models"][model]["correct"] == float(gold == pred)
        correct += gold == pred
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
        answered += bool(pred)
    same(correct / len(xs) if xs else None, metric["exact"])
    assert (tp, fp, fn, answered) == (metric["tp"], metric["fp"], metric["fn"], metric["answered"])
    same(tp / (tp + fp) if tp + fp else None, metric["precision"])
    same(tp / (tp + fn) if tp + fn else None, metric["recall"])
    same(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None, metric["f1"])


def check_binding(xs, metric):
    annotated = [x for x in xs if x["gold"]]
    subsets = {"all_annotated": annotated,
               "new_pair_known": [x for x in annotated if x["bucket"] == "new_pair_known"],
               "unknown_lemma": [x for x in annotated if x["bucket"] == "unknown_lemma"],
               "seen_pair": [x for x in annotated if x["bucket"] == "seen_pair"],
               "depth_ge2": [x for x in annotated if x["depth"] >= 2],
               "alternatives": [x for x in annotated if x["alternatives"] >= 2]}
    for model, categories in metric["models"].items():
        for group, values in categories.items():
            check_set_metrics(subsets[group], model, values)


def main():
    sources = 0
    for path in sorted((ROOT / "data").glob("*sources.json")):
        for item in read(path):
            payload = (ROOT / item["path"]).read_bytes()
            assert len(payload) == item["bytes"]
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            sources += 1
    m1 = read(ROOT / "results/001/metrics.json")
    for name, evaluation in m1["evaluations"].items():
        xs = rows(ROOT / "results/001" / (name + "_predictions.jsonl"))
        for model, groups in evaluation["models"].items():
            for group, metric in groups.items():
                selected = xs if group == "all" else [x for x in xs if x["bucket"] == group.removesuffix("_known") and (not group.endswith("_known") or x["known_lemmas"])]
                assert len(selected) == metric["n"]
                same(sum(x["models"][model]["correct"] for x in selected) / len(selected) if selected else None, metric["accuracy"])
                assert sum(x["models"][model]["correct"] == 0.5 for x in selected) == metric["ties"]
    m2 = read(ROOT / "results/002/metrics.json")
    for split in ("dev", "test"):
        check_binding(rows(ROOT / f"results/002/{split}_predictions.jsonl"), m2["evaluations"][split])
    m3, x3 = read(ROOT / "results/003/metrics.json"), rows(ROOT / "results/003/predictions.jsonl")
    for x in x3:
        assert int(hashlib.sha256(("003:" + x["doc"]).encode()).hexdigest(), 16) % 5 == x["fold"]
    check_binding(x3, m3["pooled"])
    for fold, data in m3["folds"].items():
        check_binding([x for x in x3 if x["fold"] == int(fold)], data["metrics"])
    m4, x4 = read(ROOT / "results/004/metrics.json"), rows(ROOT / "results/004/predictions.jsonl")
    check_binding(x4, m4)
    x2test = rows(ROOT / "results/002/test_predictions.jsonl")
    assert {x["id"] for x in x2test} == {x["id"] for x in x4}
    for x in x4:
        assert x["models"]["gold_object_first"]["correct"] == next(t["models"]["object_first"]["correct"] for t in x2test if t["id"] == x["id"])
    annotations = read(ROOT / "results/005/annotations.json")
    fingerprint = hashlib.sha256(json.dumps(annotations, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    m5, x5 = read(ROOT / "results/005/metrics.json"), rows(ROOT / "results/005/predictions.jsonl")
    assert fingerprint == m5["annotation_canonical_sha256"]
    assert not m5["excluded_overlap"]
    by_id = {x["id"]: x for x in annotations["items"]}
    for x in x5:
        assert x["gold"] == by_id[x["id"]]["participants"]
        assert x["status"] == by_id[x["id"]]["status"]
    clear = [x for x in x5 if x["status"] == "clear"]
    for model, metric in m5["models_clear"].items():
        check_set_metrics(clear, model, metric)
    print(f"Verified {sources} source hashes and all saved accuracy/set metrics for experiments 001-005")


if __name__ == "__main__":
    main()
