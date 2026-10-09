"""Download immutable UD sources; preserve hashes and attribution."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "syntagrus": ("UD_Russian-SynTagRus", "6377522610550b696fcc70d39074d2ce03da0e7b"),
    "gsd": ("UD_Russian-GSD", "9acc9d677327043bd416fcc89e4b3407c620d885"),
}

def main():
    manifest = []
    for name, (repo, revision) in SOURCES.items():
        api = f"https://api.github.com/repos/UniversalDependencies/{repo}/contents?ref={revision}"
        with urllib.request.urlopen(api, timeout=60) as response:
            entries = json.load(response)
        paths = sorted(x["name"] for x in entries if x["name"].endswith(".conllu") or x["name"] in ("LICENSE.txt", "README.md"))
        for filename in paths:
            url = f"https://raw.githubusercontent.com/UniversalDependencies/{repo}/{revision}/{filename}"
            target = ROOT / "data" / "raw" / name / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with urllib.request.urlopen(url, timeout=120) as response:
                    payload = response.read()
                target.write_bytes(payload)
            payload = target.read_bytes()
            manifest.append({"corpus": name, "revision": revision, "url": url,
                             "path": target.relative_to(ROOT).as_posix(), "bytes": len(payload),
                             "sha256": hashlib.sha256(payload).hexdigest()})
            print(name, filename, len(payload), flush=True)
    dest = ROOT / "data" / "sources.json"
    if dest.exists():
        previous = json.loads(dest.read_text(encoding="utf-8"))
        if manifest != previous:
            raise ValueError("Downloaded files do not match committed manifest")
    else:
        dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
