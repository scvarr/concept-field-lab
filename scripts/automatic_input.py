"""Experiment 004: fixed learned operators with external automatic basic input."""
from collections import Counter
import hashlib
import importlib.metadata
import json
import platform
import time

from conditional_operators import ConditionalOperators, training_sentences
from context_binding import ROOT, graph, interval, summary, targets
from role_transfer import sentences

MODEL_FILE = ROOT / "data/raw/parser/russian-syntagrus-ud-2.5-191206.udpipe"
MODES = ("subject_rule", "object_first", "learned_recursive", "context_global", "context_lexical")


def blank_sentence(tokens):
    from ufal.udpipe import Sentence
    sent = Sentence()
    for expected, token in enumerate(tokens, 1):
        if token["id"] != expected:
            raise ValueError("Noncontiguous token ids")
        sent.addWord(token["form"])
    return sent


def automatic_tokens(model, tokens):
    from ufal.udpipe import ProcessingError
    sent = blank_sentence(tokens)
    error = ProcessingError()
    if not model.tag(sent, model.DEFAULT, error) or not model.parse(sent, model.DEFAULT, error):
        raise RuntimeError(error.message)
    return [dict(id=w.id, form=w.form, lemma=w.lemma.lower().replace("ё", "е"), pos=w.upostag,
                 feats=w.feats, head=w.head, rel=w.deprel, deps="_") for w in list(sent.words)[1:]]


def parser_training_audit():
    ids, docs, text_hashes = set(), set(), set()
    for path in sorted((ROOT / "data/raw/syntagrus25").glob("*.conllu")):
        for metadata, _ in sentences(path):
            ids.add(metadata["sent_id"])
            docs.add(metadata["sent_id"].rsplit("_", 1)[0])
            text_hashes.add(hashlib.sha256(metadata.get("text", "").encode()).hexdigest())
    if not ids:
        raise ValueError("Missing parser historical training data")
    test_ids, test_docs, test_texts = set(), set(), set()
    for path in (ROOT / "data/raw/syntagrus").glob("*-ud-test*.conllu"):
        for metadata, _ in sentences(path):
            test_ids.add(metadata["sent_id"])
            test_docs.add(metadata["sent_id"].rsplit("_", 1)[0])
            test_texts.add(hashlib.sha256(metadata.get("text", "").encode()).hexdigest())
    audit = {"ud25_train_dev_sentences": len(ids), "ud25_train_dev_docs": len(docs),
             "test_sentence_id_overlap": len(ids & test_ids), "test_doc_overlap": len(docs & test_docs),
             "test_exact_text_overlap": len(text_hashes & test_texts), "excluded_docs": sorted(docs & test_docs)}
    return audit, docs, text_hashes


def main():
    from ufal.udpipe import Model
    started = time.monotonic()
    audit, forbidden_docs, forbidden_texts = parser_training_audit()
    ops = ConditionalOperators()
    for metadata, tokens in training_sentences():
        ops.observe(metadata, tokens)
    parser = Model.load(str(MODEL_FILE))
    if parser is None:
        raise ValueError("Cannot load model")
    dest = ROOT / "results/004"
    dest.mkdir(parents=True, exist_ok=True)
    rows, diagnostics = [], Counter()
    with (dest / "parsed_input.conllu").open("w", encoding="utf-8") as parsed_stream:
        for path in sorted((ROOT / "data/raw/syntagrus").glob("*-ud-test*.conllu")):
            for metadata, tokens in sentences(path):
                ts, nodes, children, _ = targets(metadata, tokens)
                if not ts:
                    continue
                doc = metadata["sent_id"].rsplit("_", 1)[0]
                text_hash = hashlib.sha256(metadata.get("text", "").encode()).hexdigest()
                if doc in forbidden_docs or text_hash in forbidden_texts or text_hash in ops.train_texts:
                    diagnostics["excluded_overlap_targets"] += len(ts)
                    continue
                diagnostics["sentences_processed"] += 1
                parsed = automatic_tokens(parser, tokens)
                pred_nodes, pred_children = graph(parsed)
                parsed_stream.write("# sent_id = " + metadata["sent_id"] + "\n")
                for token, pred in zip(tokens, parsed):
                    diagnostics["tokens"] += 1
                    diagnostics["correct_lemma"] += pred["lemma"] == token["lemma"]
                    diagnostics["correct_pos"] += pred["pos"] == token["pos"]
                    diagnostics["correct_head"] += pred["head"] == token["head"]
                    diagnostics["correct_head_rel"] += pred["head"] == token["head"] and pred["rel"] == token["rel"]
                    parsed_stream.write("\t".join((str(pred["id"]), pred["form"], pred["lemma"], pred["pos"], "_", pred["feats"], str(pred["head"]), pred["rel"], "_", "_")) + "\n")
                parsed_stream.write("\n")
                for t in ts:
                    diagnostics["targets"] += 1
                    target_pred = pred_nodes[t["target"]]
                    diagnostics["target_xcomp_preserved"] += target_pred["rel"] == "xcomp"
                    diagnostics["target_xcomp_head_preserved"] += target_pred["rel"] == "xcomp" and target_pred["head"] == nodes[t["target"]]["head"]
                    known = t["parent_lemma"] in ops.train_vocabulary and t["child_lemma"] in ops.train_vocabulary
                    new = (t["parent_lemma"], t["child_lemma"]) not in ops.train_pairs
                    t.update(new_pair=new, known_lemmas=known,
                             bucket="new_pair_known" if new and known else "unknown_lemma" if not known else "seen_pair")
                    t["models"] = {}
                    for prefix, ns, cs in (("gold", nodes, children), ("parsed", pred_nodes, pred_children)):
                        for mode in MODES:
                            prediction, trace = ops.bind(t["target"], ns, cs, mode)
                            t["models"][prefix + "_" + mode] = {"prediction": sorted(prediction), "trace": trace,
                                                                  "correct": float(prediction == set(t["gold"])) if t["gold"] else None}
                    rows.append(t)
                if diagnostics["sentences_processed"] % 200 == 0:
                    print("Parsed", diagnostics["sentences_processed"], "sentences", flush=True)
    annotated = [t for t in rows if t["gold"]]
    subsets = {"all_annotated": annotated,
               "new_pair_known": [t for t in annotated if t["bucket"] == "new_pair_known"],
               "depth_ge2": [t for t in annotated if t["depth"] >= 2]}
    out = {"experiment": "004", "environment": {"python": platform.python_version(), "platform": platform.platform(),
                                                  "ufal.udpipe": importlib.metadata.version("ufal.udpipe")},
           "model_sha256": hashlib.sha256(MODEL_FILE.read_bytes()).hexdigest(), "parser_audit": audit,
           "diagnostics": dict(diagnostics), "parser_quality_selected_sentences": {
               metric: diagnostics[count] / diagnostics["tokens"] for metric, count in
               (("lemma", "correct_lemma"), ("pos", "correct_pos"), ("uas", "correct_head"), ("las", "correct_head_rel"))},
           "models": {prefix + "_" + mode: {key: summary(ts, prefix + "_" + mode) for key, ts in subsets.items()}
                      for prefix in ("gold", "parsed") for mode in MODES},
           "paired": {key: {mode: interval(ts, "parsed_" + mode, "gold_" + mode) for mode in MODES} for key, ts in subsets.items()},
           "no_enhanced_answer": {"n": len(rows) - len(annotated)},
           "elapsed_seconds": round(time.monotonic() - started, 3)}
    (dest / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (dest / "predictions.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(out["models"]["parsed_context_global"]), flush=True)
    print("Finished", out["elapsed_seconds"], "seconds", flush=True)


if __name__ == "__main__":
    main()
