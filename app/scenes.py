"""Operator-authored scenes and a bounded, explicit local transition experiment.

No language understanding, physics, spreading activation or automatic inference.
All mutations run inside PermanentStore's revision transaction.
"""
import copy
from app.store import Invalid, clean, lookup, uid

LIMIT = 200  # One extraction/working set; no implicit transitive scene loading.


def empty_lab():
    return {'scenes': [], 'workspaces': [], 'currentSceneId': None}


def items(value, name, limit=10000):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, dict) for v in value):
        raise Invalid(f'{name}: нужен список объектов, предел {limit}.')
    ids = [clean(v.get('id'), name + ' ID', True, 200) for v in value]
    if len(ids) != len(set(ids)):
        raise Invalid(f'{name}: повтор ID.')
    return value


def projection(scene, through=None):
    """Replay explicit state writes/retractions; events never imply state changes."""
    current = {}
    for entry in scene['entries'][:through]:
        for ident in entry['retracts']:
            current.pop(ident, None)
        if entry['kind'] == 'state':
            for fact in entry['assertions']:
                if fact['slot']:
                    current = {k: v for k, v in current.items()
                               if (v['from'], v['slot']) != (fact['from'], fact['slot'])}
                current[fact['id']] = fact
    return list(current.values())


def signature(edge):
    return {k: edge.get(k, '') for k in ('id', 'from', 'to', 'role', 'type')}


def source_facts(scene):
    active = {f['id'] for f in projection(scene)}
    return [(e, f) for e in scene['entries'] for f in e['assertions']
            if f['id'] in active or e['kind'] == 'event']


def reachable_scenes(lab, scene, blocked=()):
    """An index of references only, never materialize their facts in a workspace."""
    seen, pending = set(), list(scene['links'])
    while pending:
        ident = pending.pop()
        if ident not in seen and ident not in blocked:
            seen.add(ident)
            pending.extend(lookup(lab['scenes'], ident, 'ссылка сцены')['links'])
    return seen


def active_context(scene):
    """The last explicit context input wins; accumulated links are not context."""
    return next((e['contextSceneId'] for e in reversed(scene['entries']) if e['kind'] == 'context'), None)


def context_sources(lab, scene):
    ident = active_context(scene)
    if ident is None:
        return set()
    # A back-reference must not reopen the dialogue's accumulated source list.
    return {ident} | reachable_scenes(lab, lookup(lab['scenes'], ident, 'действующий контекст'), blocked={scene['id']})


def structure_root(obj):
    # The template position and the content may address different graph concepts.
    return obj.get('contentConceptId', obj['conceptId'])


def continuations(workspace):
    """A directed context pair permits a step between loaded local assertions.

    Deliberately does not establish semantic applicability. The operator selects
    the bindings and the active source; no global graph traversal occurs here.
    """
    result = []
    for bundle in workspace['bundles']:
        for source in bundle['assertions']:
            if source['activation'] == 'inactive':
                continue
            for target in bundle['assertions']:
                if target['activation'] != 'inactive' or not compatible_bindings(source, target):
                    continue
                for permission in bundle['contexts']:
                    if permission['from'] == source['template']['id'] and permission['to'] == target['template']['id']:
                        result.append({'from': source['id'], 'to': target['id'], 'contextId': permission['id']})
    return result


def compatible_bindings(source, target):
    """Shared template concepts must bind the same local objects in a step.

    This conservative MVP constraint prevents a permission for screw A from
    activating a relation of screw B. It is not a general role unifier.
    """
    def bindings(fact):
        result = {}
        for end in ('from', 'to'):
            result.setdefault(fact['template'][end], set()).add(fact[end])
        return result
    left, right = bindings(source), bindings(target)
    return all(left[i] == right[i] for i in left.keys() & right.keys())


def observe(graph):
    lab = graph.get('sceneLab', empty_lab())
    return {'current': {s['id']: projection(s) for s in lab['scenes']},
            'available': {s['id']: [f['id'] for _, f in source_facts(s)] for s in lab['scenes']},
            'reachable': {s['id']: sorted(reachable_scenes(lab, s)) for s in lab['scenes']},
            'activeContext': {s['id']: active_context(s) for s in lab['scenes']},
            'contextSources': {s['id']: sorted(context_sources(lab, s)) for s in lab['scenes']},
            'continuations': {w['id']: continuations(w) for w in lab['workspaces']}}


def validate_lab(graph):
    lab = graph['sceneLab']
    if not isinstance(lab, dict) or set(lab) != set(empty_lab()):
        raise Invalid('Неверная структура сцен.')
    scenes = items(lab['scenes'], 'Сцены')
    scene_ids = {s['id'] for s in scenes}
    if lab['currentSceneId'] is not None:
        if lookup(scenes, lab['currentSceneId'], 'текущая сцена')['kind'] != 'dialogue':
            raise Invalid('Текущая сцена должна быть разговорной.')
    nodes = {n['id']: n for n in graph['nodes']}
    edges = {e['id']: e for e in graph['edges']}
    graph_ids = {v['id'] for key in ('nodes', 'edges', 'contextEdges', 'designations', 'definitionDrafts') for v in graph[key]}
    if graph_ids.intersection(scene_ids):
        raise Invalid('ID сцены совпадает с ID каркаса/черновика.')
    global_ids = graph_ids | scene_ids
    for scene in scenes:
        clean(scene.get('label'), 'обозначение сцены', True, 1000)
        if scene.get('kind') not in ('knowledge', 'dialogue'):
            raise Invalid('Назначение сцены: knowledge / dialogue.')
        links = scene.get('links')
        if not isinstance(links, list) or any(not isinstance(i, str) or i not in scene_ids for i in links) or len(links) != len(set(links)):
            raise Invalid('Неверные ссылки сцен.')
        objects = items(scene.get('objects'), 'Объекты')
        object_map = {o['id']: o for o in objects}
        for obj in objects:
            clean(obj.get('label'), 'объект', True, 1000)
            if obj.get('conceptId') not in nodes:
                raise Invalid('Сцена использует отсутствующий концепт каркаса; удаление запрещено.')
            if 'contentConceptId' in obj:
                ident = clean(obj['contentConceptId'], 'содержательный концепт', True, 200)
                if ident != obj['contentConceptId'] or ident not in nodes:
                    raise Invalid('Содержательный концепт сцены отсутствует в каркасе; удаление запрещено.')
        fact_ids = set()
        for entry in items(scene.get('entries'), 'Входы'):
            clean(entry.get('text'), 'вход', True)
            if entry.get('kind') not in ('state', 'event', 'context'):
                raise Invalid('Вид входа: state / event / context.')
            retracts = entry.get('retracts')
            if not isinstance(retracts, list) or any(not isinstance(i, str) or i not in fact_ids for i in retracts):
                raise Invalid('Снятие требует ID прежнего утверждения этой сцены.')
            for fact in items(entry.get('assertions'), 'Утверждения', LIMIT):
                if fact['id'] in fact_ids:
                    raise Invalid('Повтор ID утверждения в сцене.')
                fact_ids.add(fact['id'])
                clean(fact.get('slot'), 'слот', False, 200)
                edge = edges.get(fact.get('edgeId'))
                if not edge or edge['role'] != 'relation' or signature(edge) != fact.get('template'):
                    raise Invalid('Сцена использует изменённое/удалённое отношение каркаса. Сначала требуется явная миграция сцен.')
                for end in ('from', 'to'):
                    obj = object_map.get(fact.get(end))
                    if not obj or obj['conceptId'] != edge[end]:
                        raise Invalid('Концы заполнения не соответствуют концептам отношения каркаса.')
            if entry['kind'] == 'context':
                if entry['assertions'] or entry['retracts'] or entry.get('contextSceneId') not in scene['links']:
                    raise Invalid('Контекстный вход требует ссылку сцены без утверждений.')
                if scene['kind'] != 'dialogue' or lookup(scenes, entry['contextSceneId'], 'контекст')['kind'] != 'knowledge':
                    raise Invalid('Действующий контекст разговора должен ссылаться на сцену знаний.')
        local_ids = [o['id'] for o in objects] + [e['id'] for e in scene['entries']] + list(fact_ids)
        if len(local_ids) != len(set(local_ids)) or global_ids.intersection(local_ids):
            raise Invalid('ID сцен, объектов, входов и утверждений должны различаться.')
        global_ids.update(local_ids)
    for workspace in items(lab['workspaces'], 'Рабочие области'):
        if lookup(scenes, workspace.get('sceneId'), 'сцена рабочей области')['kind'] != 'dialogue':
            raise Invalid('Рабочая область относится к разговорной сцене.')
        clean(workspace.get('label'), 'рабочая область', True, 1000)
        revision = workspace.get('createdRevision')
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise Invalid('Неверная версия происхождения рабочей области.')
        total = 0
        for bundle in items(workspace.get('bundles'), 'Извлечения', LIMIT):
            source = lookup(scenes, bundle.get('sourceSceneId'), 'исходная сцена')
            local_objects = {v['id']: v for v in items(bundle.get('objects'), 'Рабочие объекты', LIMIT * 10)}
            object_ids = local_objects.keys()
            assertions = items(bundle.get('assertions'), 'Рабочие утверждения', LIMIT)
            total += len(assertions)
            for fact in assertions:
                if fact.get('activation') not in ('inactive', 'seed', 'context') or fact.get('from') not in object_ids or fact.get('to') not in object_ids:
                    raise Invalid('Неверное локальное состояние рабочей области.')
                origin = fact.get('origin', {})
                entry = lookup(source['entries'], origin.get('entryId'), 'вход происхождения')
                original = lookup(entry['assertions'], origin.get('assertionId'), 'утверждение происхождения')
                if fact.get('template') != original['template'] or origin.get('sceneId') != source['id']:
                    raise Invalid('Неверное происхождение рабочего утверждения.')
                for end in ('from', 'to'):
                    if local_objects[fact[end]].get('sourceObjectId') != original[end]:
                        raise Invalid('Рабочее заполнение смешивает объекты происхождения.')
            items(bundle.get('contexts'), 'Локальные разрешения', LIMIT * LIMIT)
            for context in bundle['contexts']:
                if not isinstance(context.get('from'), str) or not isinstance(context.get('to'), str):
                    raise Invalid('Неверное локальное разрешение.')
            # Copies are snapshots; no equality to the *current* graph is required.
            structural_ids = []
            for obj in bundle['objects']:
                source_obj = lookup(source['objects'], obj.get('sourceObjectId'), 'объект происхождения')
                if obj.get('conceptId') != source_obj['conceptId'] or obj.get('contentConceptId') != source_obj.get('contentConceptId'):
                    raise Invalid('Неверный концепт рабочего объекта.')
                structure = obj.get('structure')
                if not isinstance(structure, dict):
                    raise Invalid('Нет снимка структуры рабочего объекта.')
                ns = items(structure.get('nodes'), 'Копии концептов', LIMIT)
                es = items(structure.get('edges'), 'Копии компонентов', LIMIT * LIMIT)
                root = lookup(ns, structure.get('rootId'), 'корень рабочей структуры')
                if root.get('sourceId') != structure_root(obj) or any(e.get('role') != 'component' for e in es):
                    raise Invalid('Неверный обязательный состав рабочей копии.')
                from app.alpha import validate_structure
                validate_structure(ns, es)
                structural_ids.extend(v['id'] for v in [*ns, *es])
            local_ids = [bundle['id'], *object_ids, *(f['id'] for f in assertions), *structural_ids]
            if len(local_ids) != len(set(local_ids)) or global_ids.intersection(local_ids):
                raise Invalid('Рабочие экземпляры должны иметь независимые ID.')
            global_ids.update(local_ids)
        if total > LIMIT:
            raise Invalid(f'Рабочая область: предел {LIMIT} утверждений.')
        if workspace['id'] in global_ids:
            raise Invalid('Повтор ID рабочей области.')
        global_ids.add(workspace['id'])
        if not isinstance(workspace.get('trace'), list):
            raise Invalid('Нет локального журнала активации.')


def merge_lab(existing, incoming):
    result = copy.deepcopy(existing or empty_lab())
    for key in ('scenes', 'workspaces'):
        indexed = {v['id']: v for v in result[key]}
        for value in incoming[key]:
            if value['id'] in indexed and indexed[value['id']] != value:
                raise Invalid('Конфликт ID сцены/рабочей области; автоматического объединения состояний нет.')
            if value['id'] not in indexed:
                result[key].append(copy.deepcopy(value))
    if result['currentSceneId'] is None:
        result['currentSceneId'] = incoming['currentSceneId']
    return result


def structure_copy(graph, root):
    """Copy only the explicitly defined mandatory composition, bounded at 200 nodes."""
    seen, pending = set(), [root]
    while pending:
        ident = pending.pop()
        if ident in seen:
            continue
        seen.add(ident)
        if len(seen) > LIMIT:
            raise Invalid(f'Состав превышает предел извлечения {LIMIT} концептов.')
        pending.extend(e['to'] for e in graph['edges'] if e['role'] == 'component' and e['from'] == ident)
    mapping = {i: uid() for i in sorted(seen)}
    return {'rootId': mapping[root],
            'nodes': [{**copy.deepcopy(lookup(graph['nodes'], i, 'концепт')), 'id': mapping[i], 'sourceId': i}
                      for i in sorted(seen)],
            'edges': [{**copy.deepcopy(e), 'id': uid(), 'sourceId': e['id'], 'from': mapping[e['from']], 'to': mapping[e['to']]}
                      for e in graph['edges'] if e['role'] == 'component' and e['from'] in seen]}


def operate(graph, action, data, revision):
    lab = graph.setdefault('sceneLab', empty_lab())
    result = {}
    if action == 'scene_create':
        scene = {'id': uid(), 'label': clean(data.get('label'), 'обозначение', True, 1000),
                 'kind': data.get('kind'), 'objects': [], 'entries': [], 'links': []}
        lab['scenes'].append(scene)
        if scene['kind'] == 'dialogue':
            lab['currentSceneId'] = scene['id']
        result = {'sceneId': scene['id']}
    elif action == 'scene_select':
        scene = lookup(lab['scenes'], data.get('sceneId'), 'сцена')
        if scene['kind'] != 'dialogue':
            raise Invalid('Выберите разговорную сцену.')
        lab['currentSceneId'] = scene['id']
    elif action == 'scene_object':
        scene = lookup(lab['scenes'], data.get('sceneId'), 'сцена')
        obj = {'id': uid(), 'label': clean(data.get('label'), 'объект', True, 1000), 'conceptId': data.get('conceptId')}
        if 'contentConceptId' in data:
            obj['contentConceptId'] = clean(data['contentConceptId'], 'содержательный концепт', True, 200)
        scene['objects'].append(obj)
        result = {'objectId': obj['id']}
    elif action == 'scene_link':
        scene = lookup(lab['scenes'], data.get('sceneId'), 'сцена')
        target = lookup(lab['scenes'], data.get('targetId'), 'сцена назначения')
        if target['id'] == scene['id']:
            raise Invalid('Прямая самоссылка сцены не нужна; выберите другую сцену.')
        if target['id'] not in scene['links']:
            scene['links'].append(target['id'])
    elif action == 'scene_context':
        scene = lookup(lab['scenes'], data.get('sceneId'), 'сцена диалога')
        if scene['kind'] != 'dialogue':
            raise Invalid('Контекст выбирается для разговора.')
        text = clean(data.get('text'), 'контекст', True, 1000)
        if 'contextSceneId' in data:
            target = lookup(lab['scenes'], clean(data['contextSceneId'], 'ID контекста', True, 200), 'сцена контекста')
            if target['kind'] != 'knowledge':
                raise Invalid('Контекст должен быть сценой знаний.')
        else:
            matches = [s for s in lab['scenes'] if s['kind'] == 'knowledge' and s['label'].casefold() == text.casefold()]
            if len(matches) != 1:
                raise Invalid('Сцена знаний не найдена или обозначение неоднозначно. Выберите уникальное обозначение существующей сцены.')
            target = matches[0]
        if target['id'] not in scene['links']:
            scene['links'].append(target['id'])
        entry = {'id': uid(), 'text': text, 'kind': 'context', 'assertions': [], 'retracts': [], 'contextSceneId': target['id']}
        scene['entries'].append(entry)
        result = {'contextSceneId': target['id'], 'entryId': entry['id']}
    elif action == 'scene_input':
        scene = lookup(lab['scenes'], data.get('sceneId'), 'сцена')
        if data.get('kind') not in ('state', 'event'):
            raise Invalid('Назначение структурированного входа: state / event.')
        raw = data.get('assertions', [])
        if not isinstance(raw, list) or len(raw) > LIMIT:
            raise Invalid('Нужен ограниченный список заполнений.')
        assertions = []
        for fact in raw:
            if not isinstance(fact, dict):
                raise Invalid('Заполнение должно быть объектом.')
            edge = lookup(graph['edges'], fact.get('edgeId'), 'отношение каркаса')
            assertions.append({'id': uid(), 'edgeId': edge['id'], 'template': signature(edge),
                               'from': fact.get('from'), 'to': fact.get('to'),
                               'slot': clean(fact.get('slot', ''), 'слот', False, 200)})
        retracts = data.get('retracts', [])
        if not isinstance(retracts, list) or any(not isinstance(i, str) for i in retracts):
            raise Invalid('Снятия: список ID.')
        active_ids = {f['id'] for f in projection(scene)}
        if not set(retracts) <= active_ids:
            raise Invalid('Снимать можно только текущее утверждение этой сцены.')
        if not assertions and not retracts:
            raise Invalid('Задайте заполнение или явно снимите текущее утверждение.')
        entry = {'id': uid(), 'text': clean(data.get('text'), 'текст входа', True), 'kind': data['kind'],
                 'assertions': assertions, 'retracts': copy.deepcopy(retracts)}
        scene['entries'].append(entry)
        result = {'entryId': entry['id'], 'assertionIds': [a['id'] for a in assertions]}
    elif action == 'scene_workspace':
        scene = lookup(lab['scenes'], data.get('sceneId'), 'сцена разговора')
        if scene['kind'] != 'dialogue':
            raise Invalid('Рабочая область требует разговорную сцену.')
        workspace = {'id': uid(), 'sceneId': scene['id'], 'label': clean(data.get('label'), 'обозначение', True, 1000),
                     'createdRevision': revision, 'bundles': [], 'trace': []}
        lab['workspaces'].append(workspace)
        result = {'workspaceId': workspace['id']}
    elif action == 'scene_extract':
        workspace = lookup(lab['workspaces'], data.get('workspaceId'), 'рабочая область')
        dialogue = lookup(lab['scenes'], workspace['sceneId'], 'разговор')
        source = lookup(lab['scenes'], data.get('sourceSceneId'), 'сцена источник')
        if source['id'] != dialogue['id'] and source['id'] not in reachable_scenes(lab, dialogue):
            raise Invalid('Исходная сцена не входит в накопленные доступные ссылки разговора.')
        ids = data.get('assertionIds')
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise Invalid('Выберите различные ID текущих утверждений/событий для извлечения.')
        if len(ids) + sum(len(b['assertions']) for b in workspace['bundles']) > LIMIT:
            raise Invalid(f'Рабочая область: предел {LIMIT} утверждений.')
        available = {f['id']: (e, f) for e, f in source_facts(source)}
        if not set(ids) <= available.keys():
            raise Invalid('Извлекаются только текущие утверждения и явно записанные события.')
        selected = [available[i] for i in ids]
        objects = {f[end] for _, f in selected for end in ('from', 'to')}
        mapping = {i: uid() for i in sorted(objects)}
        edge_ids = {f['edgeId'] for _, f in selected}
        bundle = {'id': uid(), 'sourceSceneId': source['id'], 'sourceRevision': revision,
                  'objects': [{**copy.deepcopy(lookup(source['objects'], i, 'объект')), 'id': mapping[i],
                               'sourceObjectId': i, 'structure': structure_copy(graph, structure_root(lookup(source['objects'], i, 'объект')))}
                              for i in sorted(objects)],
                  'assertions': [{**copy.deepcopy(f), 'id': uid(), 'from': mapping[f['from']], 'to': mapping[f['to']],
                                  'activation': 'inactive', 'origin': {'sceneId': source['id'], 'entryId': e['id'],
                                  'assertionId': f['id'], 'revision': revision, 'kind': e['kind']}}
                                 for e, f in selected],
                  'contexts': [copy.deepcopy(c) for c in graph['contextEdges'] if {c['from'], c['to']} <= edge_ids]}
        workspace['bundles'].append(bundle)
        workspace['trace'].append({'op': 'extract', 'bundleId': bundle['id'], 'revision': revision})
        result = {'bundleId': bundle['id'], 'assertionIds': [f['id'] for f in bundle['assertions']]}
    elif action in ('scene_seed', 'scene_step', 'scene_reset'):
        workspace = lookup(lab['workspaces'], data.get('workspaceId'), 'рабочая область')
        facts = [f for b in workspace['bundles'] for f in b['assertions']]
        if action == 'scene_reset':
            for fact in facts:
                fact['activation'] = 'inactive'
            trace = {'op': 'reset'}
        else:
            target = lookup(facts, data.get('assertionId'), 'рабочее утверждение')
            if target['activation'] != 'inactive':
                raise Invalid('Рабочее утверждение уже активно.')
            if action == 'scene_seed':
                target['activation'] = 'seed'
                trace = {'op': 'seed', 'to': target['id'], 'reason': 'Явный выбор оператора'}
            else:
                step = next((c for c in continuations(workspace) if c['to'] == target['id'] and c['from'] == data.get('fromId') and c['contextId'] == data.get('contextId')), None)
                if step is None:
                    raise Invalid('Нет локального направленного разрешения от активного источника. Состояние не изменено.')
                target['activation'] = 'context'
                trace = {'op': 'step', **step}
        workspace['trace'].append({**trace, 'revision': revision})
    else:
        raise Invalid('Неизвестная операция сцен.')
    return result, 'Сцены MVP: ' + action
