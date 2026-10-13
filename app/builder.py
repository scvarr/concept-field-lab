"""Finite manual definition drafts and confirmed additions to an accumulation."""
import copy
import math
from uuid import uuid5, NAMESPACE_URL
from app.store import Invalid, clean, lookup, now, uid, fields

LIMITS = {'nodes': 80, 'edges': 160, 'contextEdges': 800, 'routes': 40}


def manual(acc):
    return acc.get('manual', {'nodes': [], 'edges': [], 'designations': [], 'contextEdges': []})


def validate_draft(draft):
    if not isinstance(draft, dict):
        raise Invalid('Неверный черновик.')
    clean(draft.get('id'), 'ID черновика', True, 200)
    clean(draft.get('title'), 'название определения', True, 1000)
    clean(draft.get('definition', ''), 'определение')
    for key, limit in LIMITS.items():
        if not isinstance(draft.get(key), list) or len(draft[key]) > limit:
            raise Invalid(f'Черновик: предел {key} = {limit}.')
    ids = set()
    for key in ('nodes', 'edges', 'contextEdges', 'routes'):
        for item in draft[key]:
            if not isinstance(item, dict):
                raise Invalid('В черновике ожидался объект.')
            ident = clean(item.get('id'), 'ID объекта', True, 200)
            if ident in ids:
                raise Invalid('Повтор ID в черновике.')
            ids.add(ident)
    node_ids = {n['id'] for n in draft['nodes']}
    edges = {e['id']: e for e in draft['edges']}
    for n in draft['nodes']:
        if not isinstance(n.get('existing'), bool):
            raise Invalid('Выберите новый или существующий концепт.')
        clean(n.get('designation', ''), 'обозначение', not n['existing'], 1000)
        for k in ('x', 'y'):
            if k in n and (isinstance(n[k], bool) or not isinstance(n[k], (int, float)) or not math.isfinite(n[k]) or abs(n[k]) > 100000):
                raise Invalid('Позиции должны быть конечными числами ±100000.')
    for e in draft['edges']:
        if e.get('from') not in node_ids or e.get('to') not in node_ids or not isinstance(e.get('existing'), bool):
            raise Invalid('Ребро требует два выбранных поля.')
    pairs = set()
    for c in draft['contextEdges']:
        pair = c.get('from'), c.get('to')
        if pair[0] not in edges or pair[1] not in edges or pair[0] == pair[1] or pair in pairs:
            raise Invalid('Контекст требует два разных обычных ребра без повторения пары.')
        pairs.add(pair)
    for r in draft['routes']:
        route = r.get('edgeIds')
        if not isinstance(route, list) or not route or len(route) > 40 or len(set(route)) != len(route) or any(e not in edges for e in route):
            raise Invalid('Маршрут: 1–40 различных рёбер.')
        if any(edges[a]['to'] != edges[b]['from'] for a, b in zip(route, route[1:])):
            raise Invalid('Рёбра маршрута должны последовательно соединяться.')


def validate_extension(study, identity):
    acc = study['accumulation']
    data = manual(acc)
    if not isinstance(data, dict) or set(data) != {'nodes', 'edges', 'designations', 'contextEdges'} or any(not isinstance(data[k], list) for k in data):
        raise Invalid('Неверный ручной слой полотна.')
    drafts = acc.get('definitionDrafts', [])
    if not isinstance(drafts, list) or len(drafts) > 20:
        raise Invalid('Предел эксперимента — 20 черновиков на полотно.')
    seen = set()
    for draft in drafts:
        validate_draft(draft)
        identity({'id': draft['id']})
        seen.add(draft['id'])
    edge_ids = {e['id'] for e in study['edges'] if e.get('role', 'relation') == 'relation'}
    pairs = set()
    for c in data['contextEdges']:
        identity(c)
        pair = c.get('from'), c.get('to')
        if pair[0] not in edge_ids or pair[1] not in edge_ids or pair[0] == pair[1] or pair in pairs:
            raise Invalid('Контекст полотна ссылается на неверные рёбра или повторяет пару.')
        pairs.add(pair)
    for key in data:
        for obj in data[key]:
            if obj.get('definitionId') not in seen:
                raise Invalid('Ручной объект требует сохранённого определения происхождения.')


def comparable(node):
    return {k: v for k, v in node.items() if k not in ('x', 'y', 'layoutPinned')}


def prepare(study, draft):
    """Pure preview with exactly the same validation as commit."""
    from app.accumulation import projection
    from app.store import validate
    validate_draft(draft)
    if not draft['nodes'] or not draft['definition'].strip():
        raise Invalid('Для включения нужны определение и хотя бы одно поле.')
    result = copy.deepcopy(study)
    acc = result['accumulation']
    layer = copy.deepcopy(manual(acc))
    old = {key: [o for o in layer[key] if o['definitionId'] == draft['id']] for key in layer}
    for key in layer:
        layer[key] = [o for o in layer[key] if o['definitionId'] != draft['id']]
    current_nodes = {n['id']: n for n in study['nodes']}
    current_edges = {e['id']: e for e in study['edges']}
    old_nodes = {n['id']: n for n in old['nodes']}
    new_nodes = []
    for index, n in enumerate(draft['nodes']):
        if n['existing']:
            actual = lookup(study['nodes'], n['id'], 'выбранный концепт на полотне')
            if n.get('base') is None or comparable(actual) != comparable(n['base']):
                raise Invalid('Выбранный концепт изменён; выберите его заново после просмотра.')
            # Own nodes remain owned by the original definition on reopening.
            if n['id'] in old_nodes:
                layer['nodes'].append(copy.deepcopy(old_nodes[n['id']]))
                layer['designations'].extend(copy.deepcopy(d) for d in old['designations'] if d['target'] == n['id'])
            continue
        if n['id'] in current_nodes and n['id'] not in old_nodes:
            raise Invalid('Новый ID уже существует; выберите существующий концепт.')
        origin = {'definitionId': draft['id'], 'snapshot': {'definition': draft['definition'], 'dictionaryId': n.get('dictionaryId')}}
        node = {**copy.deepcopy(old_nodes.get(n['id'], {})), 'id': n['id'], **fields({'label': '', 'designationOnly': True}),
                'designationOnly': True, 'structure': 'concept', 'origins': [origin], 'definitionId': draft['id'],
                'x': n.get('x', current_nodes.get(n['id'], {}).get('x', 260 * (index % 5))),
                'y': n.get('y', current_nodes.get(n['id'], {}).get('y', max([v.get('y', 0) for v in study['nodes']] + [0]) + 220 + 140 * (index // 5)))}
        layer['nodes'].append(node)
        previous = next((d for d in old['designations'] if d['target'] == n['id']), None)
        layer['designations'].append({'id': previous['id'] if previous else str(uuid5(NAMESPACE_URL, 'concept-field-designation:' + n['id'])), 'target': n['id'], 'text': n['designation'],
            'notes': '', 'source': 'Ручной ввод определения', 'origins': [origin], 'definitionId': draft['id']})
        new_nodes.append(n['id'])
    old_edges = {e['id']: e for e in old['edges']}
    new_edges = []
    for e in draft['edges']:
        if e['existing']:
            actual = lookup(study['edges'], e['id'], 'выбранное ребро')
            if actual['from'] != e['from'] or actual['to'] != e['to'] or actual.get('role', 'relation') != 'relation':
                raise Invalid('Выбранное ребро изменено или не является обычным.')
            if e['id'] in old_edges:
                layer['edges'].append(copy.deepcopy(old_edges[e['id']]))
            continue
        if e['id'] in current_edges and e['id'] not in old_edges:
            raise Invalid('ID нового ребра занят.')
        duplicate = [v for v in study['edges'] if v['from'] == e['from'] and v['to'] == e['to'] and v['id'] != e['id'] and v.get('role', 'relation') == 'relation']
        if duplicate and not e.get('parallelReason', '').strip():
            raise Invalid('Для этих концов уже есть ребро: повторно используйте его ID либо обоснуйте параллельное.')
        layer['edges'].append({'id': e['id'], 'from': e['from'], 'to': e['to'], 'role': 'relation', 'type': '',
            'notes': '', 'origins': [{'definitionId': draft['id'], 'snapshot': copy.deepcopy(e)}], 'definitionId': draft['id'],
            'parallelReason': clean(e.get('parallelReason', ''), 'обоснование параллельного ребра')})
        new_edges.append(e['id'])
    for c in draft['contextEdges']:
        existing = next((v for v in layer['contextEdges'] if (v['from'], v['to']) == (c['from'], c['to'])), None)
        if existing:
            if c['id'] != existing['id']:
                raise Invalid('Контекстная пара уже записана; используйте существующий ID.')
            continue
        layer['contextEdges'].append({**copy.deepcopy(c), 'definitionId': draft['id']})
    acc['manual'] = layer
    result.update(projection(acc, result))
    validate({'studies': [result], 'matches': [], 'imports': [], 'proposals': []})
    return result, {'nodes': new_nodes, 'edges': new_edges, 'contextEdges': copy.deepcopy(draft['contextEdges']),
        'removed': {key: [v['id'] for v in old[key] if not any(o['id'] == v['id'] for o in layer[key])] for key in layer},
        'reusedNodes': [n['id'] for n in draft['nodes'] if n['existing']], 'reusedEdges': [e['id'] for e in draft['edges'] if e['existing']]}


def operate(state, action, data):
    study = lookup(state['studies'], data.get('studyId'), 'полотно')
    if not study.get('accumulation'):
        raise Invalid('Выберите накопительное полотно.')
    drafts = study['accumulation'].setdefault('definitionDrafts', [])
    if action == 'definition_save':
        draft = copy.deepcopy(data.get('draft'))
        validate_draft(draft)
        existing = next((d for d in drafts if d['id'] == draft['id']), None)
        if existing:
            existing.clear()
            existing.update(draft)
        else:
            drafts.append(draft)
        return {'draftId': draft['id']}, 'Сохранён черновик определения'
    draft = lookup(drafts, data.get('draftId'), 'черновик')
    if action == 'definition_publish':
        if data.get('confirmed') is not True:
            raise Invalid('Просмотрите изменения и подтвердите включение.')
        updated, preview = prepare(study, draft)
        study.clear()
        study.update(updated)
        return preview, 'Подтверждён ручной миниграф; прежние исходники сохранены'
    raise Invalid('Неизвестная операция конструктора.')
