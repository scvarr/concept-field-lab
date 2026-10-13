"""External lexical lookup. No implicit conceptual identity or POS assignment."""
import json
from functools import lru_cache
from pathlib import Path
from app.store import clean

DATA = Path(__file__).resolve().parents[1] / 'data' / 'dictionary'


def normalized(value):
    return value.strip().casefold().replace('ё', 'е')


@lru_cache(maxsize=1)
def dictionary():
    return json.loads((DATA / 'lemmas.json').read_text(encoding='utf-8'))


def search(state, query, canvas_id=None):
    q = normalized(clean(query, 'поиск', False, 200))
    lemmas = [] if not q else [r for r in dictionary() if q in normalized(r[1])]
    lemmas.sort(key=lambda r: (normalized(r[1]) != q, not normalized(r[1]).startswith(q), r[1], r[0]))
    concepts = []
    permanent = 'studies' not in state
    for study in ([state] if permanent else state['studies']):
        terms = {}
        for d in study.get('designations', []):
            terms.setdefault(d['target'], []).append(d['text'])
        for node in study['nodes']:
            names = terms.get(node['id'], []) + ([node['label']] if node['label'] else [])
            if not q or not (q in normalized(node['id']) or any(q in normalized(t) for t in names)):
                continue
            edges = [e for e in study['edges'] if node['id'] in (e['from'], e['to'])]
            concepts.append({'studyId': study.get('id'), 'studyTitle': study.get('title', 'Постоянный граф'), 'nodeId': node['id'],
                'labels': list(dict.fromkeys(names)), 'kind': node.get('kind', ''), 'notes': node.get('notes', ''),
                'location': 'permanent' if permanent else 'canvas' if study.get('accumulation') else 'source', 'archived': study.get('archived', False),
                'selectable': permanent or study['id'] == canvas_id, 'origins': node.get('origins', []), 'edges': edges,
                'definitions': [{'id': did, 'title': p['title'], 'definition': p['definition']} for did, p in (study if permanent else study.get('accumulation', {})).get('definitionPublications', {}).items() if node['id'] in p['nodeIds']],
                'contexts': [c for c in (study if permanent else study.get('accumulation', {}).get('manual', {})).get('contextEdges', [])
                             if c['from'] in {e['id'] for e in edges} or c['to'] in {e['id'] for e in edges}]})
    concepts.sort(key=lambda c: (not c['selectable'], c['studyTitle'], c['nodeId']))
    words = [{'id': 'opencorpora:' + r[0], 'lemma': r[1], 'grammemes': r[2],
              'hasConcept': any(normalized(r[1]) == normalized(t) for c in concepts for t in c['labels'])} for r in lemmas[:60]]
    return {'words': words, 'concepts': concepts[:80], 'wordCount': len(lemmas), 'conceptCount': len(concepts),
            'multipleConcepts': len({c['nodeId'] for c in concepts}) > 1,
            'source': json.loads((DATA / 'provenance.json').read_text(encoding='utf-8'))}
