"""Evaluate frozen auxiliary LLM labels on an external corpus, never train on them."""
from collections import Counter
import hashlib
import importlib.metadata
import json
import platform
import re
import time

from automatic_input import MODEL_FILE, automatic_tokens, parser_training_audit
from conditional_operators import ConditionalOperators, training_sentences
from context_binding import ROOT, graph, summary
from role_transfer import sentences

MODES = ("subject_rule", "object_first", "learned_recursive", "context_global")


def semantic_document(sid):
    return re.sub(r"-\d+$", "", sid) if not sid.isdigit() else sid


def main():
    from ufal.udpipe import Model
    started = time.monotonic()
    dest = ROOT / "results/005"
    annotation_document = json.loads((dest / "annotations.json").read_text(encoding="utf-8"))
    annotations = annotation_document["items"]
    fingerprint = hashlib.sha256(json.dumps(annotation_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    inputs = json.loads((dest / "annotation-input.json").read_text(encoding="utf-8"))
    assert [a["id"] for a in annotations] == [t["id"] for t in inputs]
    by_id = {a["id"]: a for a in annotations}
    ops = ConditionalOperators()
    for metadata, tokens in training_sentences():
        ops.observe(metadata, tokens)
    _, parser_docs, parser_texts = parser_training_audit()
    parser = Model.load(str(MODEL_FILE))
    if parser is None:
        raise ValueError("Cannot load parser")
    rows, exclusions = [], []
    source = ROOT / "data/raw/taiga/ru_taiga-ud-test.conllu"
    for metadata, tokens in sentences(source):
        matches = [a for a in annotations if a["id"].rsplit(":", 1)[0] == metadata["sent_id"]]
        if not matches:
            continue
        text_hash = hashlib.sha256(metadata["text"].encode()).hexdigest()
        doc = semantic_document(metadata["sent_id"])
        if text_hash in ops.train_texts or text_hash in parser_texts or doc in ops.train_docs or doc in parser_docs:
            exclusions.extend(a["id"] for a in matches)
            continue
        nodes, children = graph(tokens)
        parsed = automatic_tokens(parser, tokens)
        pred_nodes, pred_children = graph(parsed)
        for annotation in matches:
            tid = int(annotation["id"].rsplit(":", 1)[1])
            row = {**annotation, "target": tid, "doc": doc, "gold": annotation["participants"],
                   "basic_graph": list(nodes.values()), "parsed_graph": list(pred_nodes.values()), "models": {}}
            for prefix, ns, cs in (("basic", nodes, children), ("parsed", pred_nodes, pred_children)):
                for mode in MODES:
                    predicted, trace = ops.bind(tid, ns, cs, mode)
                    row["models"][prefix + "_" + mode] = {"prediction": sorted(predicted), "trace": trace,
                                                            "correct": float(predicted == set(annotation["participants"])) if annotation["status"] == "clear" else None}
            rows.append(row)
    # Restore preregistered ordering, not source file order.
    order = {a["id"]: i for i, a in enumerate(annotations)}
    rows.sort(key=lambda x: order[x["id"]])
    clear = [x for x in rows if x["status"] == "clear"]
    out = {"experiment": "005", "annotation_kind": "auxiliary_LLM_not_human_gold", "frozen_annotation_commit": "c91988c",
           "annotation_canonical_sha256": fingerprint,
           "environment": {"python": platform.python_version(), "platform": platform.platform(), "ufal.udpipe": importlib.metadata.version("ufal.udpipe")},
           "statuses": dict(Counter(x["status"] for x in rows)), "excluded_overlap": exclusions,
           "models_clear": {prefix + "_" + mode: summary(clear, prefix + "_" + mode) for prefix in ("basic", "parsed") for mode in MODES},
           "nonclear_outputs": {prefix + "_" + mode: sum(bool(x["models"][prefix + "_" + mode]["prediction"]) for x in rows if x["status"] != "clear")
                                for prefix in ("basic", "parsed") for mode in MODES},
           "elapsed_seconds": round(time.monotonic() - started, 3)}
    (dest / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (dest / "predictions.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(out["models_clear"]), flush=True)
    print("Finished", out["elapsed_seconds"], "seconds", flush=True)


if __name__ == "__main__":
    main()
