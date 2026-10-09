"""Experiment 003: document cross-validation of context-conditioned binding."""
from collections import Counter, defaultdict
import hashlib
import json
import platform
import time

from context_binding import Operators, ROLES, MODES, ROOT, graph, interval, metrics, role_nodes, targets
from role_transfer import sentences

CONDITIONAL = ("context_global", "context_lexical")
ALL_MODES = MODES + CONDITIONAL


def fold_of(doc):
    return int(hashlib.sha256(("003:" + doc).encode()).hexdigest(), 16) % 5


def signature(parent, children):
    return "".join("1" if role_nodes(children, parent["id"], role) else "0" for role in ROLES) + ("1" if parent["rel"] == "xcomp" else "0")


class ConditionalOperators(Operators):
    def __init__(self):
        super().__init__()
        self.context_counts = defaultdict(Counter)
        self.lexical_context = defaultdict(Counter)

    def observe(self, metadata, tokens):
        super().observe(metadata, tokens)
        ts, nodes, children, subjects = targets(metadata, tokens)
        for t in ts:
            gold = set(t["gold"])
            if not gold:
                continue
            parent = nodes[nodes[t["target"]]["head"]]
            possible = {r: role_nodes(children, parent["id"], r) for r in ROLES}
            if not possible["nsubj"]:
                possible["nsubj"] = subjects[parent["id"]]
            matched = [r for r in ROLES if gold <= possible[r]]
            if len(matched) == 1:
                sig, role = signature(parent, children), matched[0]
                self.context_counts[sig][role] += 1
                self.lexical_context[parent["lemma"], sig][role] += 1

    def select(self, parent, child, children, mode):
        if mode not in CONDITIONAL:
            return super().select(parent, child, children, mode)
        sig = signature(parent, children)
        context = self.context_counts.get(sig, self.global_counts)
        if mode == "context_global":
            return self.majority(context)
        local = self.lexical_context.get((parent["lemma"], sig), Counter())
        total = sum(context.values())
        return max(ROLES, key=lambda r: (local[r] + 4 * context[r] / total, -ROLES.index(r)))


def training_sentences():
    for path in sorted((ROOT / "data/raw/syntagrus").glob("*-ud-train*.conllu")):
        yield from sentences(path)


def train_fold(fold):
    ops = ConditionalOperators()
    for metadata, tokens in training_sentences():
        if fold_of(metadata["sent_id"].rsplit("_", 1)[0]) != fold:
            ops.observe(metadata, tokens)
    return ops


def evaluate_fold(ops, fold):
    result, diagnostic = [], Counter()
    for metadata, tokens in training_sentences():
        doc = metadata["sent_id"].rsplit("_", 1)[0]
        if fold_of(doc) != fold:
            continue
        assert doc not in ops.train_docs
        ts, nodes, children, _ = targets(metadata, tokens)
        diagnostic["sentences"] += 1
        diagnostic["documents_check"] = fold
        if hashlib.sha256(metadata.get("text", "").encode()).hexdigest() in ops.train_texts:
            diagnostic["excluded_train_text_overlap_targets"] += len(ts)
            continue
        for t in ts:
            diagnostic["targets"] += 1
            known = t["parent_lemma"] in ops.train_vocabulary and t["child_lemma"] in ops.train_vocabulary
            new = (t["parent_lemma"], t["child_lemma"]) not in ops.train_pairs
            t.update(fold=fold, new_pair=new, known_lemmas=known,
                     bucket="new_pair_known" if new and known else "unknown_lemma" if not known else "seen_pair")
            t["signature"] = signature(nodes[nodes[t["target"]]["head"]], children)
            t["models"] = {}
            for mode in ALL_MODES:
                pred, trace = ops.bind(t["target"], nodes, children, mode)
                t["models"][mode] = {"prediction": sorted(pred), "trace": trace,
                                     "correct": float(pred == set(t["gold"])) if t["gold"] else None}
            result.append(t)
    return result, dict(diagnostic)


def all_metrics(rows):
    # Reuse experiment 002 metric routines with the explicit expanded model list.
    import context_binding as cb
    old_modes = cb.MODES
    cb.MODES = ALL_MODES
    try:
        out = metrics(rows)
    finally:
        cb.MODES = old_modes
    annotated = [t for t in rows if t["gold"]]
    new = [t for t in annotated if t["bucket"] == "new_pair_known"]
    out["conditional_paired_new_known"] = {m: {base: interval(new, m, base) for base in ("learned_recursive", "object_first", "context_global") if base != m}
                                            for m in CONDITIONAL}
    return out


def main():
    started = time.monotonic()
    dest = ROOT / "results/003"
    dest.mkdir(parents=True, exist_ok=True)
    all_rows, folds, sources = [], {}, {}
    for fold in range(5):
        ops = train_fold(fold)
        rows, diagnostic = evaluate_fold(ops, fold)
        all_rows.extend(rows)
        folds[str(fold)] = {"training": dict(ops.training_counts), "evaluation": diagnostic, "metrics": all_metrics(rows)}
        sources[str(fold)] = {"contexts": {k: dict(v) for k, v in sorted(ops.context_counts.items())},
                              "lexical_contexts": [{"lemma": l, "signature": s, "counts": dict(c)} for (l, s), c in sorted(ops.lexical_context.items())],
                              "global": dict(ops.global_counts)}
        print("fold", fold, "annotated", sum(bool(t["gold"]) for t in rows), flush=True)
    out = {"experiment": "003", "environment": {"python": platform.python_version(), "platform": platform.platform()},
           "folds": folds, "pooled": all_metrics(all_rows), "elapsed_seconds": round(time.monotonic() - started, 3)}
    (dest / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "operators.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (dest / "predictions.jsonl").open("w", encoding="utf-8") as stream:
        for row in all_rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(out["pooled"]["conditional_paired_new_known"]), flush=True)
    print("Finished", out["elapsed_seconds"], "seconds", flush=True)


if __name__ == "__main__":
    main()
