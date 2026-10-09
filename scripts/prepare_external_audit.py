"""Prepare a fixed surface-only annotation view before running binding."""
import hashlib
import json
import urllib.request

from context_binding import targets
from role_transfer import ROOT, sentences

REV = "d1e48cd29c1f19b6aad1aec361d9f724db764f66"


def main():
    manifest = []
    for name in ("ru_taiga-ud-test.conllu", "README.md", "LICENSE.txt"):
        url = f"https://raw.githubusercontent.com/UniversalDependencies/UD_Russian-Taiga/{REV}/{name}"
        path = ROOT / "data/raw/taiga" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                path.write_bytes(response.read())
        payload = path.read_bytes()
        manifest.append(dict(url=url, path=path.relative_to(ROOT).as_posix(), bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))
    dest = ROOT / "data/external-sources.json"
    if dest.exists():
        if json.loads(dest.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Source mismatch")
    else:
        dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidates = []
    stats = dict(sentences=0, tokens=0, deps_tokens=0, eligible=0)
    for metadata, tokens in sentences(ROOT / "data/raw/taiga/ru_taiga-ud-test.conllu"):
        stats["sentences"] += 1
        stats["tokens"] += len(tokens)
        stats["deps_tokens"] += sum(t["deps"] != "_" for t in tokens)
        ts, _, _, _ = targets(metadata, tokens)
        for t in ts:
            # No heads, roles or lemmas in annotator's view.
            target_form = next(x["form"] for x in tokens if x["id"] == t["target"])
            candidates.append(dict(id=t["id"], target=t["target"], target_form=target_form,
                                   text=metadata["text"], tokens=[dict(id=x["id"], form=x["form"]) for x in tokens]))
    stats["eligible"] = len(candidates)
    selected = sorted(candidates, key=lambda t: hashlib.sha256(("005:" + t["id"]).encode()).hexdigest())[:40]
    dest = ROOT / "results/005"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "annotation-input.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "coverage.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for i, t in enumerate(selected):
        print(json.dumps(dict(index=i, id=t["id"], target=t["target"], text=t["text"],
                              indexed=" ".join(str(x["id"]) + ":" + x["form"] for x in t["tokens"])), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
