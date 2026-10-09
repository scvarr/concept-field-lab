"""Experiment 002: acquire controller operators and execute on basic UD only."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import platform
import random
import time

from role_transfer import ROOT, sentences

ROLES = ("nsubj", "obj", "iobj", "obl")
MODES = ("pair_memory", "global_rule", "subject_rule", "object_first", "learned_local", "learned_recursive")


def graph(tokens):
    # Deliberately strip DEPS, morphology, forms, and all gold annotations.
    nodes = {t["id"]: {k: t[k] for k in ("id", "lemma", "pos", "head", "rel")} for t in tokens}
    children = defaultdict(list)
    for node in nodes.values():
        children[node["head"]].append(node)
    return nodes, children


def role_nodes(children, head, role):
    return {t["id"] for t in children[head] if t["rel"].split(":")[0] == role}


def enhanced_subjects(tokens):
    subjects = defaultdict(set)
    for t in tokens:
        for item in t["deps"].split("|"):
            if ":" not in item:
                continue
            h, rel = item.split(":", 1)
            if h.isdigit() and rel.split(":")[0] == "nsubj":
                subjects[int(h)].add(t["id"])
    return subjects


def targets(metadata, tokens):
    nodes, children = graph(tokens)
    subjects = enhanced_subjects(tokens)
    sid = metadata["sent_id"]
    result = []
    for child in nodes.values():
        parent = nodes.get(child["head"])
        if (child["pos"] != "VERB" or child["rel"] != "xcomp" or parent is None
                or parent["pos"] not in ("VERB", "AUX", "ADJ") or role_nodes(children, child["id"], "nsubj")):
            continue
        depth, ancestor, visited = 1, parent, {child["id"]}
        while ancestor["rel"] == "xcomp" and ancestor["head"] in nodes and ancestor["id"] not in visited:
            visited.add(ancestor["id"])
            depth += 1
            ancestor = nodes[ancestor["head"]]
        alternatives = sum(bool(role_nodes(children, parent["id"], r)) for r in ROLES)
        result.append({"id": sid + ":" + str(child["id"]),
                       "doc": sid.rsplit("_", 1)[0], "target": child["id"],
                       "parent_lemma": parent["lemma"], "child_lemma": child["lemma"],
                       "depth": depth, "alternatives": alternatives, "gold": sorted(subjects[child["id"]]),
                       "text_hash": hashlib.sha256(metadata.get("text", "").encode()).hexdigest()})
    return result, nodes, children, subjects


class Operators:
    def __init__(self):
        self.lexical = defaultdict(Counter)
        self.pairs = defaultdict(Counter)
        self.global_counts = Counter()
        self.evidence = defaultdict(list)
        self.train_vocabulary = set()
        self.train_pairs = set()
        self.train_texts = set()
        self.train_docs = set()
        self.training_counts = Counter()

    def observe(self, metadata, tokens):
        ts, nodes, children, subjects = targets(metadata, tokens)
        self.train_texts.add(hashlib.sha256(metadata.get("text", "").encode()).hexdigest())
        self.train_docs.add(metadata["sent_id"].rsplit("_", 1)[0])
        self.train_vocabulary.update(n["lemma"] for n in nodes.values() if n["pos"] in ("VERB", "AUX", "ADJ"))
        self.training_counts["sentences"] += 1
        for t in ts:
            self.training_counts["targets"] += 1
            self.train_pairs.add((t["parent_lemma"], t["child_lemma"]))
            gold = set(t["gold"])
            if not gold:
                self.training_counts["no_enhanced_answer"] += 1
                continue
            parent_id = nodes[t["target"]]["head"]
            possible = {}
            for role in ROLES:
                possible[role] = role_nodes(children, parent_id, role)
            if not possible["nsubj"]:
                possible["nsubj"] = subjects[parent_id]
            matched = [r for r in ROLES if gold and gold <= possible[r]]
            if len(matched) != 1:
                self.training_counts["unidentified_or_ambiguous_role"] += 1
                continue
            role = matched[0]
            self.lexical[t["parent_lemma"]][role] += 1
            self.pairs[t["parent_lemma"], t["child_lemma"]][role] += 1
            self.global_counts[role] += 1
            self.evidence[t["parent_lemma"]].append({"id": t["id"], "role": role})
            self.training_counts["learnable"] += 1

    @staticmethod
    def majority(counts):
        return max(ROLES, key=lambda r: (counts[r], -ROLES.index(r))) if counts else None

    def select(self, parent, child, children, mode):
        if mode == "pair_memory":
            return self.majority(self.pairs.get((parent["lemma"], child["lemma"]), Counter()))
        if mode == "global_rule":
            return self.majority(self.global_counts)
        if mode == "subject_rule":
            return "nsubj"
        if mode == "object_first":
            return next((r for r in ("obj", "iobj") if role_nodes(children, parent["id"], r)), "nsubj")
        return self.majority(self.lexical.get(parent["lemma"], self.global_counts))

    def bind(self, target, nodes, children, mode, visited=()):
        if target in visited or len(visited) >= 16:
            return set(), [{"stop": "cycle_or_depth", "target": target}]
        direct = role_nodes(children, target, "nsubj")
        if direct:
            return direct, [{"target": target, "role": "nsubj", "participants": sorted(direct), "source": "basic"}]
        child = nodes.get(target)
        if child is None or child["rel"] != "xcomp" or child["head"] not in nodes:
            return set(), [{"target": target, "stop": "no_basic_subject_or_xcomp"}]
        parent = nodes[child["head"]]
        role = self.select(parent, child, children, mode)
        if role is None:
            return set(), [{"target": target, "stop": "unseen_pair"}]
        local = role_nodes(children, parent["id"], role)
        trace = [{"target": target, "parent": parent["id"], "operator": parent["lemma"],
                  "role": role, "participants": sorted(local), "source": "basic_argument"}]
        if local:
            return local, trace
        if role == "nsubj" and mode != "learned_local":
            found, inherited = self.bind(parent["id"], nodes, children, mode, visited + (target,))
            return found, trace + inherited
        return set(), trace


def load_training():
    ops = Operators()
    for path in sorted((ROOT / "data/raw/syntagrus").glob("*-ud-train*.conllu")):
        for metadata, tokens in sentences(path):
            ops.observe(metadata, tokens)
    return ops


def evaluate(ops, split):
    result, diagnostics = [], Counter()
    for path in sorted((ROOT / "data/raw/syntagrus").glob(f"*-ud-{split}*.conllu")):
        for metadata, tokens in sentences(path):
            ts, nodes, children, _ = targets(metadata, tokens)
            diagnostics["sentences"] += 1
            if hashlib.sha256(metadata.get("text", "").encode()).hexdigest() in ops.train_texts:
                diagnostics["excluded_text_overlap_targets"] += len(ts)
                continue
            if metadata["sent_id"].rsplit("_", 1)[0] in ops.train_docs:
                raise ValueError("Document leakage")
            for t in ts:
                diagnostics["targets"] += 1
                known = t["parent_lemma"] in ops.train_vocabulary and t["child_lemma"] in ops.train_vocabulary
                new = (t["parent_lemma"], t["child_lemma"]) not in ops.train_pairs
                t["new_pair"] = new
                t["known_lemmas"] = known
                t["bucket"] = "new_pair_known" if new and known else "unknown_lemma" if not known else "seen_pair"
                t["models"] = {}
                for mode in MODES:
                    pred, trace = ops.bind(t["target"], nodes, children, mode)
                    t["models"][mode] = {"prediction": sorted(pred), "trace": trace,
                                         "correct": float(pred == set(t["gold"])) if t["gold"] else None}
                # Include only basic graph in artifact so inference can be independently replayed.
                t["basic_graph"] = list(nodes.values())
                result.append(t)
    return result, dict(diagnostics)


def summary(rows, mode):
    n, exact, tp, fp, fn, answered = len(rows), 0, 0, 0, 0, 0
    for t in rows:
        gold, pred = set(t["gold"]), set(t["models"][mode]["prediction"])
        exact += pred == gold
        answered += bool(pred)
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
    return {"n": n, "docs": len({t["doc"] for t in rows}), "exact": exact / n if n else None,
            "answered": answered, "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def interval(rows, mode, baseline):
    groups = defaultdict(list)
    for t in rows:
        groups[t["doc"]].append(t["models"][mode]["correct"] - t["models"][baseline]["correct"])
    if not groups:
        return None
    docs, rng = sorted(groups), random.Random(20261009)
    sums = {d: sum(groups[d]) for d in docs}
    vals = []
    for _ in range(2000):
        picked = [rng.choice(docs) for _ in docs]
        vals.append(sum(sums[d] for d in picked) / sum(len(groups[d]) for d in picked))
    vals.sort()
    return {"delta": sum(sums.values()) / len(rows), "ci95": [vals[50], vals[1950]], "docs": len(docs), "repeats": 2000, "seed": 20261009}


def metrics(rows):
    annotated = [t for t in rows if t["gold"]]
    subsets = {"all_annotated": annotated,
               "new_pair_known": [t for t in annotated if t["bucket"] == "new_pair_known"],
               "unknown_lemma": [t for t in annotated if t["bucket"] == "unknown_lemma"],
               "seen_pair": [t for t in annotated if t["bucket"] == "seen_pair"],
               "depth_ge2": [t for t in annotated if t["depth"] >= 2],
               "alternatives": [t for t in annotated if t["alternatives"] >= 2]}
    return {"models": {m: {k: summary(ts, m) for k, ts in subsets.items()} for m in MODES},
            "no_enhanced_answer": {"n": len(rows) - len(annotated),
                                   "predicted_nonempty": {m: sum(bool(t["models"][m]["prediction"]) for t in rows if not t["gold"]) for m in MODES}},
            "paired": {k: {baseline: interval(ts, "learned_recursive", baseline) for baseline in MODES if baseline != "learned_recursive"}
                       for k, ts in subsets.items() if k in ("new_pair_known", "depth_ge2", "alternatives")}}


def main():
    started = time.monotonic()
    ops = load_training()
    dest = ROOT / "results/002"
    dest.mkdir(parents=True, exist_ok=True)
    rules = {lemma: {"counts": dict(counts), "role": ops.majority(counts), "evidence": ops.evidence[lemma]}
             for lemma, counts in sorted(ops.lexical.items())}
    (dest / "operators.json").write_text(json.dumps({"global_counts": dict(ops.global_counts), "rules": rules}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = {"experiment": "002", "environment": {"python": platform.python_version(), "platform": platform.platform()},
           "training": dict(ops.training_counts), "rules": len(rules), "pair_rules": len(ops.pairs), "evaluations": {}}
    for split in ("dev", "test"):
        rows, diagnostics = evaluate(ops, split)
        out["evaluations"][split] = {"diagnostics": diagnostics, **metrics(rows)}
        with (dest / f"{split}_predictions.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        print(split, json.dumps(out["evaluations"][split]["models"]["learned_recursive"]), flush=True)
    out["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (dest / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Finished", out["elapsed_seconds"], "seconds", flush=True)


if __name__ == "__main__":
    main()
