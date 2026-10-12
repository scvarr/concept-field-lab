"""Finite experiment 001. No external models, labels or test-trained features."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import time

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("nsubj", "obj")


def sentences(path):
    metadata, tokens = {}, []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            line = line.rstrip("\n")
            if not line:
                if tokens:
                    yield metadata, tokens
                metadata, tokens = {}, []
            elif line.startswith("# ") and " = " in line:
                key, value = line[2:].split(" = ", 1)
                metadata[key] = value
            elif not line.startswith("#"):
                columns = line.split("\t")
                if columns[0].isdigit():
                    tokens.append({"id": int(columns[0]), "form": columns[1],
                                   "lemma": columns[2].lower().replace("ё", "е"),
                                   "pos": columns[3], "feats": columns[5],
                                   "head": int(columns[6]), "rel": columns[7], "deps": columns[8]})
    if tokens:
        yield metadata, tokens


def observations(metadata, tokens):
    children = defaultdict(list)
    for token in tokens:
        children[token["head"]].append(token)
    arcs, triples = [], []
    for verb in tokens:
        dependents = children[verb["id"]]
        if (verb["pos"] != "VERB" or verb["lemma"] == "_"
                or "Voice=Pass" in verb["feats"]
                or any(t["rel"] in ("nsubj:pass", "aux:pass") or t["lemma"] in ("не", "ни") for t in dependents)):
            continue
        by_role = {role: [t for t in dependents if t["rel"] == role] for role in ROLES}
        for role, ts in by_role.items():
            for token in ts:
                if token["pos"] == "NOUN" and token["lemma"] != "_":
                    arcs.append((verb["lemma"], token["lemma"], ROLES.index(role)))
        if not all(len(by_role[role]) == 1 for role in ROLES):
            continue
        subj, obj = [by_role[role][0] for role in ROLES]
        if subj["pos"] != "NOUN" or obj["pos"] != "NOUN" or "_" in (subj["lemma"], obj["lemma"]) or subj["lemma"] == obj["lemma"]:
            continue
        sent_id = metadata.get("sent_id", "unknown")
        # SynTagRus identifiers document.xml_sentence; GSD has no document grouping.
        doc = sent_id.rsplit("_", 1)[0] if ".xml_" in sent_id else sent_id
        triples.append({"id": sent_id + ":" + str(verb["id"]), "doc": doc,
                        "v": verb["lemma"], "s": subj["lemma"], "o": obj["lemma"],
                        "text_hash": hashlib.sha256(metadata.get("text", "").encode()).hexdigest()})
    return arcs, triples


def load(corpus, split):
    arcs, triples, texts, docs = [], [], set(), set()
    total = 0
    for path in sorted((ROOT / "data/raw" / corpus).glob(f"*-ud-{split}*.conllu")):
        for metadata, tokens in sentences(path):
            total += 1
            a, t = observations(metadata, tokens)
            arcs.extend(a)
            triples.extend(t)
            texts.add(hashlib.sha256(metadata.get("text", "").encode()).hexdigest())
            sid = metadata.get("sent_id", "unknown")
            docs.add(sid.rsplit("_", 1)[0] if ".xml_" in sid else sid)
    if not total:
        raise ValueError(f"No input: {corpus} {split}")
    return arcs, triples, texts, docs, total


class Memory:
    def __init__(self, arcs):
        self.pair = defaultdict(lambda: [0, 0])
        self.noun = defaultdict(lambda: [0, 0])
        self.verb = Counter()
        contexts = defaultdict(Counter)
        for v, n, r in arcs:
            self.pair[v, n][r] += 1
            self.noun[n][r] += 1
            self.verb[v] += 1
            contexts[n][v, r] += 1
        vocab = {n for n, rs in self.noun.items() if sum(rs) >= 3}
        counts = Counter()
        df = Counter()
        for n in vocab:
            counts.update(contexts[n])
            df.update(contexts[n].keys())
        self.profiles, self.inverted = {}, defaultdict(list)
        for n in sorted(vocab):
            vector = {c: (1 + math.log(count)) * (1 + math.log((len(vocab) + 1) / (df[c] + 1)))
                      for c, count in contexts[n].items() if counts[c] >= 3}
            norm = math.sqrt(sum(x * x for x in vector.values()))
            if not norm:
                continue
            vector = {c: x / norm for c, x in vector.items()}
            self.profiles[n] = vector
            for c, x in vector.items():
                self.inverted[c].append((n, x))
        self.cache = {}

    def prior(self, n):
        a, b = self.noun.get(n, (0, 0))
        return (a + 1) / (a + b + 2)

    def nearest(self, n):
        if n not in self.cache:
            scores = defaultdict(float)
            for context, x in self.profiles.get(n, {}).items():
                for other, y in self.inverted[context]:
                    if other != n:
                        scores[other] += x * y
            self.cache[n] = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:50]
        return self.cache[n]

    def probability(self, v, n, mode, k=20, strength=5):
        prior = self.prior(n)
        if mode == "noun_prior":
            return prior, False
        a, b = self.pair.get((v, n), (0, 0))
        if mode == "pair_memory":
            return (a + prior) / (a + b + 1), False
        num, den = 0.0, 0.0
        for other, sim in self.nearest(n)[:k]:
            x, y = self.pair.get((v, other), (0, 0))
            num += sim * x
            den += sim * (x + y)
        if not den:
            return (a + prior) / (a + b + 1), False
        return (a + prior + strength * num / den) / (a + b + 1 + strength), True

    def evaluate(self, triples, mode, k=20, strength=5):
        result = []
        for t in triples:
            ps, ss = self.probability(t["v"], t["s"], mode, k, strength)
            po, so = self.probability(t["v"], t["o"], mode, k, strength)
            margin = ps - po  # sign equals log joint-role odds difference
            correct = 0.5 if abs(margin) <= 1e-12 else float(margin > 0)
            result.append({**t, "correct": correct, "margin": margin, "transfer_support": ss or so})
        return result


def categorize(triples, memory, train_triples):
    seen = {(t["v"], t["s"], t["o"]) for t in train_triples}
    out = []
    for t in triples:
        missing = sum((t["v"], t[n]) not in memory.pair for n in ("s", "o"))
        bucket = "both_pairs_new" if missing == 2 else "one_pair_new" if missing == 1 else "new_triple" if (t["v"], t["s"], t["o"]) not in seen else "seen_triple"
        out.append({**t, "bucket": bucket, "known_lemmas": t["v"] in memory.verb and t["s"] in memory.noun and t["o"] in memory.noun})
    return out


def summaries(predictions):
    groups = {"all": predictions}
    for bucket in ("both_pairs_new", "one_pair_new", "new_triple", "seen_triple"):
        groups[bucket] = [p for p in predictions if p["bucket"] == bucket]
        groups[bucket + "_known"] = [p for p in groups[bucket] if p["known_lemmas"]]
    return {key: {"n": len(xs), "docs": len({x["doc"] for x in xs}),
                  "accuracy": sum(x["correct"] for x in xs) / len(xs) if xs else None,
                  "ties": sum(x["correct"] == 0.5 for x in xs),
                  "transfer_support": sum(x["transfer_support"] for x in xs)} for key, xs in groups.items()}


def paired_interval(first, second, bucket="both_pairs_new", repeats=2000):
    groups = defaultdict(list)
    assert [x["id"] for x in first] == [x["id"] for x in second]
    for a, b in zip(first, second):
        if a["bucket"] == bucket:
            groups[a["doc"]].append(a["correct"] - b["correct"])
    if not groups:
        return None
    docs = sorted(groups)
    rng = random.Random(20261009)
    samples = []
    for _ in range(repeats):
        picked = [groups[rng.choice(docs)] for _ in docs]
        samples.append(sum(sum(x) for x in picked) / sum(len(x) for x in picked))
    samples.sort()
    return {"delta": sum(sum(x) for x in groups.values()) / sum(len(x) for x in groups.values()),
            "ci95": [samples[int(0.025 * repeats)], samples[int(0.975 * repeats)]],
            "docs": len(docs), "repeats": repeats, "seed": 20261009}


def main():
    started = time.monotonic()
    train_arcs, train_triples, train_texts, train_docs, ntrain = load("syntagrus", "train")
    memory = Memory(train_arcs)
    dev_data = load("syntagrus", "dev")
    dev = categorize([t for t in dev_data[1] if t["text_hash"] not in train_texts], memory, train_triples)
    grid = []
    for k in (5, 20, 50):
        for strength in (1, 5, 20):
            metric = summaries(memory.evaluate(dev, "transfer", k, strength))["both_pairs_new"]["accuracy"]
            grid.append({"k": k, "strength": strength, "dev_accuracy": metric})
    selected = max(grid, key=lambda x: (x["dev_accuracy"], -x["strength"], -x["k"]))
    out = {"experiment": "001", "environment": {"python": platform.python_version(), "platform": platform.platform()},
           "train": {"sentences": ntrain, "arcs": len(train_arcs), "triples": len(train_triples),
                     "nouns": len(memory.noun), "verbs": len(memory.verb), "profiles": len(memory.profiles),
                     "documents": len(train_docs)}, "grid": grid, "selected": selected, "evaluations": {}}
    dest = ROOT / "results/001"
    dest.mkdir(parents=True, exist_ok=True)
    for corpus, split in (("syntagrus", "dev"), ("syntagrus", "test"), ("gsd", "test")):
        raw = dev_data if (corpus, split) == ("syntagrus", "dev") else load(corpus, split)
        ts = categorize([t for t in raw[1] if t["text_hash"] not in train_texts], memory, train_triples)
        preds = {mode: memory.evaluate(ts, mode, selected["k"], selected["strength"]) for mode in ("noun_prior", "pair_memory", "transfer")}
        key = f"{corpus}_{split}"
        out["evaluations"][key] = {"sentences": raw[4], "raw_triples": len(raw[1]),
                                   "excluded_train_text_overlap": len(raw[1]) - len(ts),
                                   "document_overlap": len(raw[3] & train_docs),
                                   "models": {mode: summaries(ps) for mode, ps in preds.items()},
                                   "transfer_minus_prior": paired_interval(preds["transfer"], preds["noun_prior"]),
                                   "transfer_minus_memory": paired_interval(preds["transfer"], preds["pair_memory"])}
        with (dest / (key + "_predictions.jsonl")).open("w", encoding="utf-8") as stream:
            for i, t in enumerate(ts):
                record = {**t, "models": {m: {f: ps[i][f] for f in ("correct", "margin", "transfer_support")} for m, ps in preds.items()}}
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        print(key, json.dumps(out["evaluations"][key]["transfer_minus_prior"]), flush=True)
    out["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (dest / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Finished", out["elapsed_seconds"], "seconds", selected, flush=True)


if __name__ == "__main__":
    main()
