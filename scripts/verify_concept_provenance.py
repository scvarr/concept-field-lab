"""Independent checks on saved M016 GUI exports and evidence hashes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/manual/evidence/concept-provenance'


def main():
    def read(name):
        return json.loads((EVIDENCE / name).read_text(encoding='utf-8-sig'))
    checks = []
    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)
    report = read('report.json')
    check(report['ok'] and not report['errors'], 'GUI successful without JavaScript errors')
    exported, again = read('permanent.json'), read('reexport.json')
    state = exported['state']
    check(exported['version'] == again['version'] == 2, 'JSON v2 unchanged')
    check(state == again['state'], 'Exact roundtrip state')
    check(any(d.get('history') == exported['history'] for d in again['importedHistory']), 'Full original history archived')
    ids = report['ids']
    nodes = {n['id']: n for n in state['nodes']}
    check(len(nodes) == 4 and len(set(ids.values())) == 4, 'Four separate concept IDs')
    check({d['target'] for d in state['designations'] if d['text'] == 'деталь'} == {ids[k] for k in ('first', 'second', 'third')}, 'Three same-designation nodes')
    for key in ('first', 'second', 'third'):
        check(bool(nodes[ids[key]]['origins'][0]['snapshot']['definition']), f'{key}: creation text saved')
    check(nodes[ids['first']]['origins'][0]['snapshot']['source']['revision'] == '42', 'Creation source revision retained')
    check(nodes[ids['second']]['origins'][0]['snapshot']['source'] is None, 'Absent source retained')
    check('КОНЕЦ ПОЛНОГО ТЕКСТА' in nodes[ids['third']]['origins'][0]['snapshot']['definition'], 'Long source text retained fully')
    second = nodes[ids['second']]
    check('живопись' in second['origins'][0]['snapshot']['definition'] and 'реставрации' in state['definitionPublications'][second['definitionId']]['definition'], 'Republication preserves original while updating publication')
    reuse = [p for did, p in state['definitionPublications'].items() if ids['first'] in p['nodeIds'] and did != nodes[ids['first']]['definitionId']]
    check(len(reuse) == 1 and reuse[0]['title'] == 'Винт', 'Reuse is separate publication, no added creation origin')
    check(len(nodes[ids['first']]['origins']) == 1, 'Reuse does not duplicate creation context')
    check(next(n for n in read('missing-origin.json')['state']['nodes'] if n['id'] == ids['first'])['origins'] == [], 'Missing-origin fixture explicit')
    check(read('baseline-origin-loss.json')['creationSnapshotReplaced'], 'Baseline loss reproduced')
    for name in ('regression-captions.json', 'regression-designations.json', 'regression-overview.json'):
        check(read(name)['ok'], name + ' successful')
    hashes = {}
    for p in sorted(EVIDENCE.iterdir()):
        if p.name == 'verification.json' or not p.is_file():
            continue
        data = p.read_bytes()
        if p.suffix in ('.json', '.txt'):
            data = data.replace(b'\r\n', b'\n')
        hashes[p.name] = hashlib.sha256(data).hexdigest()
    result = {'ok': True, 'checks': checks, 'sha256GitNormalized': hashes}
    (EVIDENCE / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(checks)} checks passed; {len(hashes)} evidence hashes recorded')


if __name__ == '__main__':
    main()
