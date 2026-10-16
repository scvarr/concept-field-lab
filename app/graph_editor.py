"""Explicit edits of the canonical graph; no semantic identification."""
import copy
from app.store import Invalid, clean, lookup

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


def changes(before, after):
    result = {}
    for key in COLLECTIONS:
        a = {v['id']: v for v in before[key]}
        b = {v['id']: v for v in after[key]}
        result[key] = [{'id': i, 'before': a.get(i), 'after': b.get(i)}
                       for i in sorted(a.keys() | b.keys()) if a.get(i) != b.get(i)]
    changed_edges = {v['id'] for v in result['edges']}
    changed_nodes = {v['id'] for v in result['nodes']}
    changed_nodes.update(v[side]['from'] for v in result['edges'] for side in ('before', 'after')
                         if v[side] and v[side]['role'] == 'component')
    structural = ancestors(before, changed_nodes) | ancestors(after, changed_nodes)
    review_edges = changed_edges | {e['id'] for s in (before, after) for e in s['edges']
                                    if structural & {e['from'], e['to']}}
    result['affectedContexts'] = [copy.deepcopy(c) for c in after['contextEdges']
                                  if review_edges & {c['from'], c['to']}]
    return result



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
            if op.get('deleteSource'):
                if any(source in (e['from'], e['to']) for e in result['edges']) or any(d['target'] == source for d in result['designations']):
                    raise Invalid('У исходного ID остались рёбра или обозначения; удаление запрещено.')
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
                value = {**previous, **value}
                if 'origins' in previous:
                    value['origins'] = copy.deepcopy(previous['origins'])
                result[key][result[key].index(previous)] = value
            else:
                result['operatorVersion'] = 5
                value['origins'] = [{'operation': 'graph_editor', 'source': 'Ручной редактор постоянного графа'}]
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
    validate_graph(result)
    return result, changes(state, result)
