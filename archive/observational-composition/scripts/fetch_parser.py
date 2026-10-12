"""Immutable model mirror and historical training set for overlap audit."""
import hashlib
import json
import urllib.request

from role_transfer import ROOT

MODEL_REV = "17d6bbfb7f138f9ba2cf04692f15d892becf0246"
UD_REV = "de62ad531ce770b026b5dd97d82911810d45ba95"


def main():
    files = [(f"https://raw.githubusercontent.com/jwijffels/udpipe.models.ud.2.5/{MODEL_REV}/inst/udpipe-ud-2.5-191206/{name}", ROOT / "data/raw/parser" / name)
             for name in ("russian-syntagrus-ud-2.5-191206.udpipe", "README", "LICENSE")]
    files.extend((f"https://raw.githubusercontent.com/UniversalDependencies/UD_Russian-SynTagRus/{UD_REV}/{name}", ROOT / "data/raw/syntagrus25" / name)
                 for name in ("ru_syntagrus-ud-train.conllu", "ru_syntagrus-ud-dev.conllu"))
    manifest = []
    for url, target in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read()
            target.write_bytes(data)
        data = target.read_bytes()
        manifest.append({"url": url, "path": target.relative_to(ROOT).as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        print(target.name, len(data), flush=True)
    dest = ROOT / "data/parser-sources.json"
    if dest.exists():
        if json.loads(dest.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Source mismatch")
    else:
        dest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
