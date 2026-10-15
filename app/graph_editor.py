"""Explicit edits of the canonical graph; no semantic identification."""
import copy
from app.store import Invalid, clean, lookup, uid

COLLECTIONS = ('nodes', 'edges', 'contextEdges', 'designations')


def ancestors(state, node_ids):
    """Structural dependency only: do not traverse ordinary semantic relations."""
    parents = {}
    for e in state['edges']:
        if e['role'] == 'component':
            parents.setdefault(e['to'], []).append(e['from'])
    seen, pending = set(node_ids), list(node_ids)
    while pending:
        for parent in parents.get(pending.pop(), []):
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return seen


def usages(state, node_id):
    lookup(state['nodes'], node_id, 'концепт')
    edges = [e for e in state['edges'] if node_id in (e['from'], e['to'])]
    edge_ids = {e['id'] for e in edges}
    structural = ancestors(state, [node_id])
    indirect = [e for e in state['edges'] if e['id'] not in edge_ids and structural & {e['from'], e['to']}]
    review_edges = edge_ids | {e['id'] for e in indirect}
    return {'nodeId': node_id, 'edges': copy.deepcopy(edges),
            'ancestorIds': sorted(structural - {node_id}), 'indirectEdges': copy.deepcopy(indirect),
            'contextEdges': [copy.deepcopy(c) for c in state['contextEdges'] if review_edges & {c['from'], c['to']}],
            'designations': [copy.deepcopy(d) for d in state['designations'] if d['target'] == node_id],
            'definitions': {k: copy.deepcopy(p) for k, p in state['definitionPublications'].items()
                            if structural & set(p['nodeIds']) or review_edges & set(p['edgeIds'] + p.get('componentIds', []))},
            'drafts': [d['id'] for d in state['definitionDrafts'] if any(n['id'] == node_id for n in d['nodes'])]}


def changes(before, after):
    result = {}
    for key in COLLECTIONS:
        a = {v['id']: v for v in before[key]}
        b = {v['id']: v for v in after[key]}
        result[key] = [{'id': i, 'before': a.get(i), 'after': b.get(i)}
                       for i in sorted(a.keys() | b.keys()) if a.get(i) != b.get(i)]
    result['definitions'] = [{'id': i, 'before': before['definitionPublications'].get(i),
                              'after': after['definitionPublications'].get(i)}
                             for i in sorted(before['definitionPublications'].keys() | after['definitionPublications'].keys())
                             if before['definitionPublications'].get(i) != after['definitionPublications'].get(i)]
    changed_edges = {v['id'] for v in result['edges']}
    changed_nodes = {v['id'] for v in result['nodes']}
    changed_nodes.update(v[side]['from'] for v in result['edges'] for side in ('before', 'after')
                         if v[side] and v[side]['role'] == 'component')
    structural = ancestors(before, changed_nodes) | ancestors(after, changed_nodes)
    review_edges = changed_edges | {e['id'] for s in (before, after) for e in s['edges']
                                    if structural & {e['from'], e['to']}}
    result['affectedContexts'] = [copy.deepcopy(c) for c in after['contextEdges']
                                  if review_edges & {c['from'], c['to']}]
    # Include definitions whose referenced objects changed without changing membership.
    touched = {v['id'] for key in COLLECTIONS for v in result[key]}
    result['affectedDefinitions'] = {i: copy.deepcopy(p) for i, p in after['definitionPublications'].items()
                                     if (touched | structural) & set(p['nodeIds'] + p['edgeIds'] + p.get('componentIds', []) + p['contextIds'])}
    a = {d['id']: d for d in before['definitionDrafts']}
    b = {d['id']: d for d in after['definitionDrafts']}
    def summary(d):
        return None if d is None else {'title': d['title'], 'graphStale': d.get('graphStale'),
                                      'nodeIds': [n['id'] for n in d['nodes']],
                                      'mode': 'область общего графа' if 'graphBase' in d else 'черновик определения'}
    result['drafts'] = [{'id': i, 'before': summary(a.get(i)), 'after': summary(b.get(i))}
                        for i in sorted(a.keys() | b.keys()) if a.get(i) != b.get(i)]
    return result


def synchronize_publications(state):
    """Membership is a current index; origin snapshots and definition prose stay historical."""
    nodes = {n['id'] for n in state['nodes']}
    edges = {e['id']: e for e in state['edges']}
    contexts = {c['id'] for c in state['contextEdges']}
    for did, p in state['definitionPublications'].items():
        ids = list(p['nodeIds'])
        selected = set(p['edgeIds'] + p.get('componentIds', [])) & edges.keys()
        p['edgeIds'] = [i for i in edges if i in selected and edges[i]['role'] == 'relation']
        components = [i for i in edges if i in selected and edges[i]['role'] == 'component']
        if components or 'componentIds' in p:
            p['componentIds'] = components
        for i in selected:
            ids.extend([edges[i]['from'], edges[i]['to']])
        p['nodeIds'] = list(dict.fromkeys(i for i in ids if i in nodes))
        p['contextIds'] = [i for i in p['contextIds'] if i in contexts]


def invalidate_drafts(state, before, except_id=None):
    delta = changes(before, state)
    touched = {v['id'] for key in COLLECTIONS for v in delta[key]}
    owners = {v[side]['definitionId'] for key in COLLECTIONS for v in delta[key]
              for side in ('before', 'after') if v[side] and 'definitionId' in v[side]}
    touched.update(end for v in delta['edges'] for side in ('before', 'after') if v[side]
                   for end in (v[side]['from'], v[side]['to']))
    for draft in state['definitionDrafts']:
        if draft['id'] == except_id:
            continue
        own = {v['id'] for key in ('nodes', 'edges', 'contextEdges') for v in draft[key]}
        # A designation changes no owned node fields, and is independently edited.
        # Legacy reuse already validates its saved node base and edge endpoints at
        # prepare time; explicit ID refresh remains a valid way to review it.
        # Owned objects have no such base, so they require the persistent barrier.
        if (draft.get('graphBase') and touched & own) or draft['id'] in owners:
            base = draft.get('graphBase')
            if base and clean_region(draft):
                ids = [n['id'] for n in base['nodes'] if any(v['id'] == n['id'] for v in state['nodes'])]
                selected_edges = {e['id'] for e in base['edges']}
                for e in state['edges']:
                    if e['id'] in selected_edges:
                        ids.extend([e['from'], e['to']])
                ids = list(dict.fromkeys(ids))
                if ids and len(ids) <= 80:
                    fresh = checkout(state, ids, draft['id'])
                    if len(fresh['edges']) <= 160 and len(fresh['contextEdges']) <= 800:
                        fresh.update(title=draft['title'], definition=draft['definition'])
                        draft.clear()
                        draft.update(fresh)
                        continue
            draft['graphStale'] = 'Общий граф изменён. Черновик сохранён; откройте актуальную область отдельно и перенесите нужные правки.'


def clean_region(draft):
    def plain(v):
        return {k: x for k, x in v.items() if k not in ('existing', 'designation', 'designations', 'dictionaryId', 'base')}
    base = draft.get('graphBase')
    return bool(base) and not draft.get('graphStale') and all([plain(v) for v in draft[k]] == base[k] for k in base)


def prepare(state, data):
    """Pure, deterministic preview and commit path with global integrity validation."""
    from app.permanent import validate_graph
    result = copy.deepcopy(state)
    operations = data.get('operations')
    if not isinstance(operations, list) or not operations or len(operations) > 1000:
        raise Invalid('Нужно от 1 до 1000 явных операций.')
    for op in operations:
        if not isinstance(op, dict):
            raise Invalid('Ожидалась операция.')
        action, key = op.get('op'), op.get('collection')
        if action == 'redirect':
            source, target = op.get('source'), op.get('target')
            if source == target:
                raise Invalid('Исходный и целевой ID должны различаться.')
            lookup(result['nodes'], source, 'исходный концепт')
            lookup(result['nodes'], target, 'целевой концепт')
            selected = op.get('uses', [])
            if not isinstance(selected, list) or any(not isinstance(u, dict) for u in selected) or len(selected) != len({(u.get('id'), u.get('end')) for u in selected}):
                raise Invalid('Повтор или неверный список использований.')
            for use in selected:
                edge = lookup(result['edges'], use.get('id'), 'используемое ребро')
                end = use.get('end')
                if end not in ('from', 'to') or edge[end] != source:
                    raise Invalid('Использование изменилось; пересмотрите преобразование.')
                edge[end] = target
            for ident in op.get('designationIds', []):
                d = lookup(result['designations'], ident, 'обозначение')
                if d['target'] != source:
                    raise Invalid('Обозначение больше не адресует исходный ID.')
                d['target'] = target
            # Explicit selection for direct membership uses (no incident edge).
            for did in op.get('definitionIds', []):
                p = result['definitionPublications'].get(did)
                if not p or source not in p['nodeIds']:
                    raise Invalid('Неверное использование в определении.')
                p['nodeIds'] = list(dict.fromkeys(target if n == source else n for n in p['nodeIds']))
            if op.get('deleteSource'):
                if any(source in (e['from'], e['to']) for e in result['edges']) or any(d['target'] == source for d in result['designations']):
                    raise Invalid('У исходного ID остались рёбра или обозначения; удаление запрещено.')
                if any(source in p['nodeIds'] for p in result['definitionPublications'].values()):
                    raise Invalid('Остались использования ID в определениях; выберите их явно.')
                result['nodes'] = [n for n in result['nodes'] if n['id'] != source]
            continue
        if key not in COLLECTIONS:
            raise Invalid('Неверная коллекция объектов.')
        if action == 'delete':
            ident = op.get('id')
            lookup(result[key], ident, 'объект')
            result[key] = [v for v in result[key] if v['id'] != ident]
        elif action == 'put':
            value = copy.deepcopy(op.get('value'))
            if not isinstance(value, dict):
                raise Invalid('Нужен объект.')
            clean(value.get('id'), 'ID', True, 200)
            previous = next((v for v in result[key] if v['id'] == value['id']), None)
            if previous:
                # Provenance cannot be replaced by an object form.
                value = {**previous, **value, 'definitionId': previous['definitionId']}
                if 'origins' in previous:
                    value['origins'] = copy.deepcopy(previous['origins'])
                result[key][result[key].index(previous)] = value
            else:
                did = data.get('definitionId')
                draft = lookup(result['definitionDrafts'], did, 'черновик происхождения')
                value.update(definitionId=did)
                value['origins'] = [{'definitionId': did, 'snapshot': {'definition': draft['definition'],
                                     'source': copy.deepcopy(draft.get('source')), 'operation': 'graph_editor'}}]
                result[key].append(value)
        else:
            raise Invalid('Неизвестная операция редактора.')
    # No cascading deletion: caller must explicitly include every dependent object.
    previous_edges = {e['id'] for e in state['edges']}
    for edge in result['edges']:
        if edge['id'] not in previous_edges and edge.get('role') == 'relation':
            if any(e['id'] != edge['id'] and (e['from'], e['to'], e.get('role')) == (edge['from'], edge['to'], 'relation') for e in result['edges']):
                if not clean(edge.get('parallelReason', ''), 'обоснование параллельного ребра').strip():
                    raise Invalid('Для этих концов уже есть отношение: повторно используйте его ID либо обоснуйте параллельное.')
    synchronize_publications(result)
    validate_graph(result)
    invalidate_drafts(result, state, data.get('draftId'))
    return result, changes(state, result)


def checkout(state, node_ids, draft_id=None):
    if not isinstance(node_ids, list) or not node_ids or len(set(node_ids)) != len(node_ids) or len(node_ids) > 80:
        raise Invalid('Область: от 1 до 80 различных ID.')
    nodes = [copy.deepcopy(lookup(state['nodes'], i, 'концепт области')) for i in node_ids]
    edges = [copy.deepcopy(e) for e in state['edges'] if e['from'] in node_ids and e['to'] in node_ids]
    edge_ids = {e['id'] for e in edges}
    contexts = [copy.deepcopy(c) for c in state['contextEdges'] if {c['from'], c['to']} <= edge_ids]
    return {'id': draft_id or uid(), 'title': 'Область постоянного графа', 'definition': 'Явное редактирование выбранной области общего графа.',
            'nodes': [{**n, 'existing': False, 'designation': '', 'designations': []} for n in nodes],
            'edges': [{**e, 'existing': False} for e in edges], 'contextEdges': contexts, 'routes': [],
            'graphBase': {'nodes': nodes, 'edges': edges, 'contextEdges': copy.deepcopy(contexts)}}


def prepare_draft(state, draft):
    base = draft['graphBase']
    operations = []
    for key in ('nodes', 'edges', 'contextEdges'):
        old = {v['id']: v for v in base[key]}
        actual = {v['id']: v for v in state[key]}
        pending = {v['id']: v for v in draft[key]}
        for ident, value in old.items():
            if actual.get(ident) != value:
                raise Invalid('Область устарела: общий объект изменён или удалён. Черновик сохранён.')
            if ident not in pending:
                operations.append({'op': 'delete', 'collection': key, 'id': ident})
        for ident, value in pending.items():
            if key == 'nodes':
                if value.get('existing'):
                    if ident not in actual or value.get('base') != actual[ident]:
                        raise Invalid('Повторно выбранный ID изменён.')
                    continue
                value = {k: copy.deepcopy(v) for k, v in value.items() if k not in ('existing', 'designation', 'designations', 'dictionaryId', 'base')}
                value = {'label': '', 'designationOnly': True, 'structure': 'concept', 'kind': '', 'notes': '', 'x': 0, 'y': 0, **value}
            elif key == 'edges':
                value = {k: copy.deepcopy(v) for k, v in value.items() if k != 'existing'}
                value = {'role': 'relation', 'type': '', 'notes': '', **value}
                if pending[ident].get('existing') and ident not in old:
                    if ident not in actual or any(value.get(k) != actual[ident].get(k) for k in ('from', 'to', 'role')):
                        raise Invalid('Повторно выбранное ребро изменено.')
                    continue
            if ident not in old and ident in actual:
                raise Invalid('Новый ID уже существует; выберите существующий ID.')
            if ident not in old or any(value.get(k) != old[ident].get(k) for k in value):
                operations.append({'op': 'put', 'collection': key, 'value': value})
            if key == 'nodes' and ident not in old:
                for alias in pending[ident].get('designations', []):
                    operations.append({'op': 'put', 'collection': 'designations', 'value': {**alias, 'target': ident, 'notes': alias.get('notes', ''), 'source': 'Редактор области'}})
    if not operations:
        return copy.deepcopy(state), changes(state, state)
    result, _ = prepare(state, {'operations': operations, 'definitionId': draft['id'], 'draftId': draft['id']})
    result['definitionPublications'][draft['id']] = {
        'title': draft['title'], 'definition': draft['definition'],
        'nodeIds': [v['id'] for v in draft['nodes']],
        'edgeIds': [v['id'] for v in draft['edges'] if v.get('role', 'relation') == 'relation'],
        'componentIds': [v['id'] for v in draft['edges'] if v.get('role') == 'component'],
        'contextIds': [v['id'] for v in draft['contextEdges']]}
    from app.permanent import validate_graph
    validate_graph(result)
    return result, changes(state, result)
