"""Reduce OpenCorpora XML to an offline lemma index; never touches graph data."""
import argparse
import bz2
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def build_package(tools, output):
    import sys
    sys.path.insert(0, str(tools.resolve()))
    import pymorphy3
    import pymorphy3_dicts_ru
    from collections import Counter
    data = Path(pymorphy3_dicts_ru.get_path())
    morph = pymorphy3.MorphAnalyzer()
    rows = set()
    for word, (paradigm, index) in morph.dictionary.words.iteritems():
        if index == 0:
            tag = morph.dictionary.build_tag_info(paradigm, index)
            rows.add((word, tuple(sorted(tag.grammemes))))
    rows = [[hashlib.sha256((word + '\t' + ','.join(tags)).encode()).hexdigest()[:20], word, list(tags)] for word, tags in sorted(rows)]
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    (output / 'lemmas.json').write_bytes(payload)
    metadata = {'source': 'OpenCorpora / pymorphy3-dicts-ru', 'url': 'https://pypi.org/project/pymorphy3-dicts-ru/2.4.417150.4580142/',
        'upstreamUrl': 'https://opencorpora.org/?page=downloads', 'license': 'CC BY-SA 3.0 (data); MIT (package code)',
        'licenseUrl': 'https://creativecommons.org/licenses/by-sa/3.0/', 'packageVersion': '2.4.417150.4580142',
        'toolVersions': {'pymorphy3': pymorphy3.__version__, 'dawg2-python': '0.9.0'},
        'dictionary': dict(json.loads((data / 'meta.json').read_text(encoding='utf-8'))), 'entries': len(rows),
        'posCounts': dict(Counter(morph.TagClass(','.join(r[2])).POS for r in rows)),
        'inputSha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data.iterdir()) if p.is_file()},
        'lemmasSha256': hashlib.sha256(payload).hexdigest(),
        'transformation': 'Enumerate compiled words DAWG, retain paradigm index 0 only; deduplicate (normal form, grammemes). External lexical IDs are hashes, not original XML lemma IDs. No predictions, inflected forms, definitions or graph nodes.'}
    (output / 'provenance.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(rows)} entries; sha256 {metadata["lemmasSha256"]}')


def build(source, output):
    rows = []
    with bz2.open(source, 'rb') as stream:
        events = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(events)
        revision = dict(root.attrib)
        for event, element in events:
            if event == 'end' and element.tag == 'lemma':
                lemma = element.find('l')
                rows.append([element.attrib['id'], lemma.attrib['t'], [g.attrib['v'] for g in lemma.findall('g')]])
                element.clear()
    rows.sort(key=lambda row: (row[1].casefold(), row[0]))
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    (output / 'lemmas.json').write_bytes(payload)
    metadata = {'source': 'OpenCorpora', 'url': 'https://opencorpora.org/files/export/dict/dict.opcorpora.xml.bz2',
                'license': 'CC BY-SA 3.0', 'licenseUrl': 'https://creativecommons.org/licenses/by-sa/3.0/',
                'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'dictionary': revision,
                'entries': len(rows), 'lemmasSha256': hashlib.sha256(payload).hexdigest(),
                'transformation': 'Only l/@t, lemma/@id and l/g/@v; inflected f forms and links omitted. No definitions.'}
    (output / 'provenance.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path, nargs='?')
    parser.add_argument('--package-tools', type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/dictionary'))
    args = parser.parse_args()
    if args.package_tools:
        build_package(args.package_tools, args.output)
    elif args.source:
        build(args.source, args.output)
    else:
        parser.error('Provide XML bz2 or --package-tools')
