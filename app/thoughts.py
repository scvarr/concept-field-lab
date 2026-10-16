"""Manual phrase construction. No language model, classifier or inferred semantics."""
import copy
import hashlib
import json
from app.store import Invalid, clean, lookup, uid
from app.scenes import empty_lab, signature, compatible_bindings, items


def empty():
    return {'drafts': [], 'templates': [], 'candidates': [], 'currentDraftId': None}


def geometry(config):
    """Identity includes ordered local endpoints, edge IDs and context direction."""
    return {'nodes': [(n['id'], n['conceptId'], n['required']) for n in config['nodes']],
            'edges': [(e['id'], e['edgeId'], e['from'], e['to'], e['required']) for e in config['edges']],
            'contexts': [(c['id'], c['contextId'], c['from'], c['to'], c['required']) for c in config['contexts']]}


def missing(draft):
    config = draft['config']
    contract = draft.get('contract') or config
    gaps = []
    for key in ('nodes', 'edges', 'contexts'):
        current = {v['id']: v for v in config[key]}
        for item in contract[key]:
            if not item['required']:
                continue
            value = current.get(item['id'])
            if not value or not value['included'] or (key == 'nodes' and not value['value'].strip()):
                gaps.append(item['id'])
    for n in config['nodes']:
        if n['included'] and not n['value'].strip() and n['id'] not in gaps:
            gaps.append(n['id'])
    return gaps


def content_digest(draft):
    config = copy.deepcopy(draft['config'])
    for n in config['nodes']:
        for key in ('x', 'y'):
            n.pop(key, None)
    return hashlib.sha256(json.dumps([draft['text'], config, draft['anchors']], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def uncovered(draft):
    active = {v['id'] for k in draft['config'] for v in draft['config'][k] if v['included']}
    covered = {i for a in draft['anchors'] if a['id'] in active for i in range(a['start'], a['end'])}
    result = []
    for i, ch in enumerate(draft['text']):
        if not ch.isspace() and i not in covered:
            if result and result[-1]['end'] == i:
                result[-1]['end'] = i + 1
                result[-1]['text'] += ch
            else:
                result.append({'start': i, 'end': i + 1, 'text': ch})
    return result


def content_gaps(draft):
    edges = {e['id']: e for e in draft['config']['edges']}
    return [n['id'] for n in draft['config']['nodes'] if n['included'] and n.get('bindingRequired') and not any(
        i in edges and edges[i]['included'] and n['id'] in (edges[i]['from'], edges[i]['to'])
        for i in n.get('contentEdges', []))]


def continuations(draft):
    config = draft['config']
    nodes = {n['id']: n for n in config['nodes']}
    links = {e['id']: e for e in config['edges']}
    result = []
    for c in config['contexts']:
        if not c['included']:
            continue
        source, target = links[c['from']], links[c['to']]
        if (source['included'] and not target['included']
                and all(nodes[i]['included'] and nodes[i]['value'].strip()
                        for e in (source, target) for i in (e['from'], e['to']))
                and compatible_bindings(source, target)):
            result.append({'from': source['id'], 'to': target['id'], 'contextId': c['id']})
    return result


def validate_config(graph, config):
    if not isinstance(config, dict) or set(config) != {'nodes', 'edges', 'contexts'}:
        raise Invalid('Неверная конфигурация мысли.')
    permanent_nodes = {n['id'] for n in graph['nodes']}
    nodes = {n['id']: n for n in items(config['nodes'], 'Элементы мысли', 80)}
    edges = {e['id']: e for e in items(config['edges'], 'Связи мысли', 160)}
    contexts = items(config['contexts'], 'Разрешения мысли', 800)
    ids = [i['id'] for k in config for i in config[k]]
    if len(ids) != len(set(ids)):
        raise Invalid('Локальные ID конструкции должны различаться.')
    for key in config:
        for item in config[key]:
            if type(item.get('required')) is not bool or type(item.get('included')) is not bool:
                raise Invalid('Обязательность и включение задаются явно.')
    for n in nodes.values():
        if n.get('conceptId') not in permanent_nodes:
            raise Invalid('Элемент мысли ссылается на отсутствующий концепт.')
        clean(n.get('value'), 'локальное значение', False, 10000)
        if 'bindingRequired' in n and type(n['bindingRequired']) is not bool:
            raise Invalid('Необходимость содержательной привязки задаёт оператор.')
        if 'contentEdges' in n and (not isinstance(n['contentEdges'], list) or any(
                i not in edges or n['id'] not in (edges[i]['from'], edges[i]['to']) for i in n['contentEdges'])):
            raise Invalid('Содержательная привязка должна адресовать обычное локальное ребро этого элемента.')
        for key in ('x', 'y'):
            v = n.get(key, 0)
            if type(v) not in (int, float) or not -100000 <= v <= 100000:
                raise Invalid('Неверная позиция элемента мысли.')
    for e in edges.values():
        edge = lookup(graph['edges'], e.get('edgeId'), 'ребро мысли')
        if edge['role'] != 'relation' or signature(edge) != e.get('template'):
            raise Invalid('Ребро конструкции изменено; требуется явное уточнение конструкции.')
        for end in ('from', 'to'):
            if e.get(end) not in nodes or nodes[e[end]]['conceptId'] != edge[end]:
                raise Invalid('Локальные концы не соответствуют обычному ребру.')
            if e['included'] and not nodes[e[end]]['included']:
                raise Invalid('Включённое ребро требует включить оба локальных конца.')
        if e.get('activation') not in ('direct', 'context'):
            raise Invalid('Активация использования: direct / context.')
    for c in contexts:
        permission = lookup(graph['contextEdges'], c.get('contextId'), 'разрешение мысли')
        if c.get('template') != {k: permission[k] for k in ('id', 'from', 'to')}:
            raise Invalid('Контекстное разрешение конструкции изменено.')
        if any(c.get(end) not in edges or edges[c[end]]['edgeId'] != permission[end] for end in ('from', 'to')):
            raise Invalid('Контекст связывает локальные использования соответствующих рёбер.')


def validate(graph):
    lab = graph['thoughtLab']
    if not isinstance(lab, dict) or set(lab) != set(empty()):
        raise Invalid('Неверная структура разборов.')
    templates = items(lab['templates'], 'Шаблоны мыслей', 1000)
    drafts = items(lab['drafts'], 'Разборы', 1000)
    candidates = items(lab['candidates'], 'Гипотезы контекста', 1000)
    top_ids = [v['id'] for k in ('drafts', 'templates', 'candidates') for v in lab[k]]
    graph_ids = {v['id'] for k in ('nodes', 'edges', 'contextEdges', 'designations', 'definitionDrafts') for v in graph[k]}
    if len(top_ids) != len(set(top_ids)) or graph_ids.intersection(top_ids):
        raise Invalid('ID операторских записей должны различаться.')
    if lab['currentDraftId'] is not None:
        lookup(drafts, lab['currentDraftId'], 'текущий разбор')
    for t in templates:
        clean(t.get('label'), 'название конструкции', True, 1000)
        if type(t.get('version')) is not int or t['version'] < 1:
            raise Invalid('Неверная версия шаблона.')
        validate_config(graph, t['config'])
        if any(n.get('sceneObjectId') for n in t['config']['nodes']):
            raise Invalid('Шаблон не должен связывать конкретные экземпляры сцены.')
    for d in drafts:
        clean(d.get('text'), 'исходная фраза', False, 10000)
        if d.get('status') not in ('draft', 'complete'):
            raise Invalid('Неверный статус мысли.')
        validate_config(graph, d['config'])
        if d.get('templateRef'):
            if not any(t['id'] == d['templateRef']['id'] for t in templates):
                archive = d.get('templateArchive')
                if not archive or archive['id'] != d['templateRef']['id']:
                    raise Invalid('Нет выбранного шаблона или его сохранённого снимка.')
                validate_config(graph, archive['config'])
        if d.get('contract'):
            validate_config(graph, d['contract'])
            for key in ('nodes', 'edges', 'contexts'):
                current = {v['id']: v for v in d['config'][key]}
                for v in d['contract'][key]:
                    if v['required']:
                        actual = current.get(v['id'])
                        fields = {'nodes': ('conceptId',), 'edges': ('edgeId', 'from', 'to', 'template'),
                                  'contexts': ('contextId', 'from', 'to', 'template')}[key]
                        if not actual or not actual['required'] or any(actual[k] != v[k] for k in fields):
                            raise Invalid('Нельзя заменить обязательную структуру выбранной конструкции; сохраните новый шаблон явно.')
                    if key == 'nodes' and v.get('bindingRequired') and not current.get(v['id'], {}).get('bindingRequired'):
                        raise Invalid('Необходимую содержательную привязку нельзя снять обычным сохранением.')
        target_scene = None
        if d.get('sceneId'):
            target_scene = lookup(graph.get('sceneLab', empty_lab())['scenes'], d['sceneId'], 'сцена разбора')
        for n in d['config']['nodes']:
            if n.get('sceneObjectId'):
                if target_scene is None:
                    raise Invalid('Повторное использование объекта требует выбранную сцену.')
                obj = lookup(target_scene['objects'], n['sceneObjectId'], 'выбранный экземпляр')
                if obj['conceptId'] != n['conceptId'] or obj['label'] != n['value']:
                    raise Invalid('Нельзя переносить значение или концепт между сценическими экземплярами.')
        selection = d.get('selection')
        if (not isinstance(selection, list) or len(selection) != 2
                or any(type(i) is not int for i in selection) or not 0 <= selection[0] <= selection[1] <= len(d['text'])):
            raise Invalid('Неверные границы фрагмента.')
        local = {v['id'] for k in d['config'] for v in d['config'][k]}
        if not isinstance(d.get('anchors'), list) or len(d['anchors']) > 10000:
            raise Invalid('Не более 10000 соответствий фрагментов.')
        for a in d['anchors']:
            if (a.get('id') not in local or type(a.get('start')) is not int or type(a.get('end')) is not int
                    or not 0 <= a['start'] < a['end'] <= len(d['text'])):
                raise Invalid('Неверное соответствие текста и локального ID.')
        if d['status'] == 'complete':
            if 'objectBindings' in d and 'representation' not in d:
                raise Invalid('Новое сценическое заполнение требует отдельного подтверждения содержания.')
            if missing(d) or not any(n['included'] for n in d['config']['nodes']):
                raise Invalid('Неполная обязательная структура не является завершённой мыслью.')
            scene = lookup(graph.get('sceneLab', empty_lab())['scenes'], d['sceneId'], 'сцена мысли')
            entry = lookup(scene['entries'], d['entryId'], 'вход мысли')
            if entry['text'] != d['text'] or entry.get('thoughtId') != d['id']:
                raise Invalid('Неверное происхождение завершённой мысли.')
            if 'objectBindings' in d:
                bindings = d['objectBindings']
                by_local = {b['localId']: lookup(scene['objects'], b['objectId'], 'экземпляр мысли') for b in bindings}
                objects = list(by_local.values())
                if len(bindings) != len(by_local):
                    raise Invalid('Повтор локального ключа сценического использования.')
            else:
                objects = [o for o in scene['objects'] if o.get('thoughtId') == d['id']]
                by_local = {o.get('localId'): o for o in objects}
            expected_nodes = [n for n in d['config']['nodes'] if n['included']]
            if len(objects) != len(expected_nodes) or set(by_local) != {n['id'] for n in expected_nodes}:
                raise Invalid('Сценические экземпляры не соответствуют завершённой конструкции.')
            for n in expected_nodes:
                if by_local[n['id']]['conceptId'] != n['conceptId'] or by_local[n['id']]['label'] != n['value']:
                    raise Invalid('Локальное значение или концепт мысли изменены без явного нового разбора.')
            facts = {f.get('localId'): f for f in entry['assertions']}
            expected_edges = [e for e in d['config']['edges'] if e['included']]
            if len(entry['assertions']) != len(expected_edges) or set(facts) != {e['id'] for e in expected_edges}:
                raise Invalid('Сценические использования не соответствуют завершённой конструкции.')
            for e in expected_edges:
                f = facts[e['id']]
                if (f['edgeId'] != e['edgeId'] or f['activation'] != e['activation']
                        or any(f[end] != by_local[e[end]]['id'] for end in ('from', 'to'))):
                    raise Invalid('Смешаны локальные привязки или активации завершённой мысли.')
            if 'representation' in d and (not d['representation'].get('confirmed')
                    or d['representation'].get('digest') != content_digest(d) or content_gaps(d) or uncovered(d)):
                raise Invalid('Представление содержания не подтверждено или изменилось.')
    validate_inclusions(graph, lab)
    for c in candidates:
        for k in ('from', 'to'):
            if lookup(graph['edges'], c.get(k), 'ребро гипотезы')['role'] != 'relation':
                raise Invalid('Гипотеза связывает только обычные рёбра.')
        clean(c.get('reason'), 'основание гипотезы', True, 10000)
        if c.get('status') not in ('pending', 'accepted', 'rejected'):
            raise Invalid('Неверное решение по гипотезе.')
        if c['status'] != 'pending':
            clean(c.get('decision'), 'решение оператора', True, 10000)
        if c['status'] == 'accepted' and not any(e['from'] == c['from'] and e['to'] == c['to'] for e in graph['contextEdges']):
            raise Invalid('Принятие требует отдельно созданного оператором контекстного разрешения.')


def validate_inclusions(graph, lab):
    scenes = graph.get('sceneLab', empty_lab())['scenes']
    for scene in scenes:
        included = set()
        for entry in scene['entries']:
            if 'sourceEntryId' not in entry:
                continue
            draft = lookup(lab['drafts'], entry.get('thoughtId'), 'происхождение включения')
            if (scene['kind'] != 'knowledge' or draft['status'] != 'complete'
                    or draft['id'] in included or entry.get('sourceSceneId') != draft['sceneId']
                    or entry['sourceEntryId'] != draft['entryId']):
                raise Invalid('Неверное или повторное включение разбора в сцену знаний.')
            included.add(draft['id'])
            source = lookup(scenes, draft['sceneId'], 'исходная сцена включения')
            original = lookup(source['entries'], draft['entryId'], 'исходный вход включения')
            if entry['text'] != original['text'] or entry['kind'] != original['kind'] or entry['retracts']:
                raise Invalid('Включение должно сохранять исходный текст и характер утверждения.')
            if type(entry.get('includedRevision')) is not int or entry['includedRevision'] < 0:
                raise Invalid('Нет версии происхождения включения.')
            source_objects = {o['id']: o for o in source['objects']}
            copies = {o['id']: o for o in scene['objects']}
            facts = {f['localId']: f for f in original['assertions']}
            if len(entry['assertions']) != len(facts) or {f.get('localId') for f in entry['assertions']} != set(facts):
                raise Invalid('Включение изменило состав утверждений.')
            for fact in entry['assertions']:
                old = facts[fact['localId']]
                if any(fact.get(k) != old.get(k) for k in ('edgeId', 'template', 'activation', 'thoughtId', 'slot')):
                    raise Invalid('Включение изменило исходное отношение.')
                for end in ('from', 'to'):
                    obj = copies[fact[end]]
                    origin = source_objects[old[end]]
                    if obj.get('sourceObjectId') != origin['id'] or any(obj.get(k) != origin.get(k) for k in ('conceptId', 'label')):
                        raise Invalid('Включение смешало независимые экземпляры.')


def operate(graph, action, data, revision):
    lab = graph.setdefault('thoughtLab', empty())
    result = {}
    if action == 'thought_new':
        graph['operatorVersion'] = 5
        if not data.get('sceneId'):
            scene_lab = graph.setdefault('sceneLab', empty_lab())
            scene = next((s for s in scene_lab['scenes'] if s['id'] == scene_lab['currentSceneId'] and s['kind'] == 'dialogue'), None)
            if scene is None:
                scene = {'id': uid(), 'label': 'Текущая динамическая сцена', 'kind': 'dialogue', 'objects': [], 'entries': [], 'links': []}
                scene_lab['scenes'].append(scene)
                scene_lab['currentSceneId'] = scene['id']
        d = {'id': uid(), 'text': clean(data.get('text', ''), 'фраза', False, 10000), 'status': 'draft',
             'config': {'nodes': [], 'edges': [], 'contexts': []}, 'selection': [0, 0], 'anchors': [],
             'templateRef': None, 'contract': None, 'createdRevision': revision, 'trace': [],
             'sceneId': data.get('sceneId') or graph.get('sceneLab', {}).get('currentSceneId'),
             'representation': {'confirmed': False}}
        if data.get('templateId'):
            t = lookup(lab['templates'], data['templateId'], 'шаблон')
            d['config'] = copy.deepcopy(t['config'])
            for key in d['config']:
                for item in d['config'][key]:
                    item['included'] = item['required']
                    if key == 'nodes':
                        item['value'] = ''
                        item.pop('sceneObjectId', None)
                    if key == 'edges':
                        item['activation'] = 'direct'
            # Required edges require endpoints even when those are marked optional.
            for e in d['config']['edges']:
                if e['included']:
                    for n in d['config']['nodes']:
                        if n['id'] in (e['from'], e['to']):
                            n['included'] = True
            d['contract'] = copy.deepcopy(t['config'])
            d['templateRef'] = {'id': t['id'], 'version': t['version']}
        lab['drafts'].append(d)
        lab['currentDraftId'] = d['id']
        result['draftId'] = d['id']
    elif action == 'thought_select':
        lab['currentDraftId'] = lookup(lab['drafts'], data.get('draftId'), 'разбор')['id']
    elif action == 'thought_close':
        lab['currentDraftId'] = None
    elif action == 'thought_include':
        d = lookup(lab['drafts'], data.get('draftId'), 'разбор')
        if d['status'] != 'complete':
            raise Invalid('В сцену знаний включается завершённый разбор.')
        scenes = graph['sceneLab']['scenes']
        source = lookup(scenes, d['sceneId'], 'исходная сцена')
        original = lookup(source['entries'], d['entryId'], 'исходный вход')
        if data.get('sceneId'):
            target = lookup(scenes, data['sceneId'], 'сцена знаний')
            if target['kind'] != 'knowledge':
                raise Invalid('Выберите сцену знаний.')
        else:
            target = {'id': uid(), 'label': clean(data.get('label'), 'название сцены', True, 1000),
                      'kind': 'knowledge', 'objects': [], 'entries': [], 'links': []}
            scenes.append(target)
        previous = next((e for e in target['entries'] if e.get('thoughtId') == d['id']), None)
        if previous:
            result.update(sceneId=target['id'], entryId=previous['id'], alreadyIncluded=True)
        else:
            mapping = {}
            bindings = d.get('objectBindings', [{'localId': o.get('localId'), 'objectId': o['id']}
                                               for o in source['objects'] if o.get('thoughtId') == d['id']])
            for binding in bindings:
                if binding['objectId'] in mapping:
                    continue
                obj = copy.deepcopy(lookup(source['objects'], binding['objectId'], 'исходный объект'))
                old_id = obj['id']
                obj.update(id=uid(), thoughtId=d['id'], sourceObjectId=old_id)
                mapping[old_id] = obj['id']
                target['objects'].append(obj)
            entry = copy.deepcopy(original)
            entry.update(id=uid(), sourceSceneId=source['id'], sourceEntryId=original['id'],
                         includedRevision=revision, retracts=[])
            for fact in entry['assertions']:
                fact.update(id=uid(), **{end: mapping[fact[end]] for end in ('from', 'to')})
            target['entries'].append(entry)
            result.update(sceneId=target['id'], entryId=entry['id'], alreadyIncluded=False)
    elif action == 'thought_revise':
        original = lookup(lab['drafts'], data.get('draftId'), 'разбор')
        d = copy.deepcopy(original)
        d.update(id=uid(), status='draft', revisedFrom=original['id'], representation={'confirmed': False})
        for key in ('entryId', 'completedRevision', 'objectBindings'):
            d.pop(key, None)
        for n in d['config']['nodes']:
            n.pop('sceneObjectId', None)
        for e in d['config']['edges']:
            e['activation'] = 'direct'
        d['trace'] = [{'revision': revision, 'decision': 'Оператор создал новый разбор на основе прежнего', 'originThoughtId': original['id']}]
        lab['drafts'].append(d)
        lab['currentDraftId'] = d['id']
        graph['operatorVersion'] = 5
        result['draftId'] = d['id']
    elif action == 'thought_alias':
        node = lookup(graph['nodes'], data.get('nodeId'), 'концепт')
        node['operatorAlias'] = clean(data.get('alias'), 'рабочий alias', False, 1000)
    elif action == 'thought_candidate':
        lab['candidates'].append({'id': uid(), 'from': data.get('from'), 'to': data.get('to'),
                                  'reason': clean(data.get('reason'), 'основание', True, 10000),
                                  'status': 'pending', 'createdRevision': revision})
    elif action == 'thought_decide':
        c = lookup(lab['candidates'], data.get('candidateId'), 'гипотеза')
        if c['status'] != 'pending' or data.get('status') not in ('accepted', 'rejected'):
            raise Invalid('Нужно явное решение по открытой гипотезе.')
        c.update(status=data['status'], decision=clean(data.get('decision'), 'решение', True, 10000), decidedRevision=revision)
    elif action in ('thought_save', 'thought_template', 'thought_complete', 'thought_step', 'thought_detach', 'thought_confirm'):
        d = lookup(lab['drafts'], data.get('draftId'), 'разбор')
        if d['status'] != 'draft':
            raise Invalid('Завершённый разбор сохранён в истории. Создайте новое применение.')
        if action == 'thought_detach':
            d['editingTemplateRef'] = copy.deepcopy(d['templateRef'])
            d['trace'].append({'revision': revision, 'decision': 'Оператор явно начал уточнение структуры',
                               'templateRef': copy.deepcopy(d['templateRef'])})
            d.update(templateRef=None, contract=None)
        elif action == 'thought_save':
            before_digest = content_digest(d)
            if 'config' in data and isinstance(data['config'], dict):
                previous = {e['id']: e for e in d['config']['edges']}
                for e in data['config'].get('edges', []):
                    if isinstance(e, dict) and e.get('activation') == 'context':
                        old = previous.get(e.get('id'))
                        if not old or old.get('activation') != 'context' or any(old[k] != e.get(k) for k in ('edgeId', 'from', 'to', 'included')):
                            raise Invalid('Контекстная активация требует отдельной команды доступного продолжения.')
            for key in ('text', 'config', 'selection', 'anchors'):
                if key in data:
                    d[key] = copy.deepcopy(data[key])
            if content_digest(d) != before_digest:
                d['representation'] = {'confirmed': False}
            if 'sceneId' in data:
                if any(n.get('sceneObjectId') for n in d['config']['nodes']) and data['sceneId'] != d.get('sceneId'):
                    raise Invalid('Сначала снимите привязки к экземплярам прежней сцены.')
                d['sceneId'] = data['sceneId']
            graph['operatorVersion'] = 5
        elif action == 'thought_confirm':
            if data.get('confirmed') is not True or missing(d) or content_gaps(d) or uncovered(d):
                raise Invalid('Представление неполно: проверьте обязательные позиции, содержательные связи и несопоставленные фрагменты.')
            graph['operatorVersion'] = 5
            d['representation'] = {'confirmed': True, 'digest': content_digest(d), 'revision': revision}
        elif action == 'thought_template':
            validate_config(graph, d['config'])
            config = copy.deepcopy(d['config'])
            if 'selection' in data:
                selected = data['selection']
                if not isinstance(selected, list) or any(not isinstance(v, str) for v in selected):
                    raise Invalid('Выбор шаблона должен содержать локальные ID.')
                for key in config:
                    config[key] = [v for v in config[key] if v['id'] in selected]
            if not config['nodes']:
                raise Invalid('Пустая конструкция не является шаблоном мысли.')
            validate_config(graph, config)
            for key in config:
                for item in config[key]:
                    if key == 'nodes':
                        item['value'] = ''
                        item.pop('sceneObjectId', None)
            if data.get('templateId'):
                t = lookup(lab['templates'], data['templateId'], 'уточняемый шаблон')
                t.update(config=config, version=t['version'] + 1, label=clean(data.get('label'), 'название', True, 1000))
            else:
                t = {'id': uid(), 'label': clean(data.get('label'), 'название', True, 1000), 'version': 1,
                     'config': config, 'createdRevision': revision}
                lab['templates'].append(t)
            d['templateRef'] = {'id': t['id'], 'version': t['version']}
            d['contract'] = copy.deepcopy(config)
            result['templateId'] = t['id']
        elif action == 'thought_step':
            candidate = next((v for v in continuations(d) if v['to'] == data.get('targetId') and v['contextId'] == data.get('contextId')), None)
            if not candidate:
                raise Invalid('Продолжение недоступно для этих локальных привязок.')
            target = lookup(d['config']['edges'], candidate['to'], 'локальное ребро')
            target.update(included=True, activation='context')
            d['representation'] = {'confirmed': False}
            d['trace'].append({**candidate, 'revision': revision, 'decision': 'Явная команда оператора'})
        else:
            if not d['text'].strip() or not any(n['included'] for n in d['config']['nodes']) or missing(d):
                raise Invalid('Неполная мысль: заполните обязательную структуру. Черновик сохранён.')
            if (not d.get('representation', {}).get('confirmed')
                    or d['representation'].get('digest') != content_digest(d) or content_gaps(d) or uncovered(d)):
                raise Invalid('Полнота шаблона не подтверждает содержание. Сопоставьте фрагменты и подтвердите необходимые связи.')
            lab_scene = graph.setdefault('sceneLab', empty_lab())
            scene_id = data.get('sceneId') or d.get('sceneId') or lab_scene['currentSceneId']
            if any(n.get('sceneObjectId') for n in d['config']['nodes']) and scene_id != d.get('sceneId'):
                raise Invalid('Экземпляр нельзя перенести в другую сцену.')
            if scene_id:
                scene = lookup(lab_scene['scenes'], scene_id, 'сцена')
            else:
                scene = {'id': uid(), 'label': 'Ручные мысли', 'kind': 'dialogue', 'objects': [], 'entries': [], 'links': []}
                lab_scene['scenes'].append(scene)
                lab_scene['currentSceneId'] = scene['id']
            mapping = {n['id']: n.get('sceneObjectId') or uid() for n in d['config']['nodes'] if n['included']}
            for n in d['config']['nodes']:
                if n['included'] and not n.get('sceneObjectId'):
                    scene['objects'].append({'id': mapping[n['id']], 'conceptId': n['conceptId'], 'label': n['value'],
                                             'thoughtId': d['id'], 'localId': n['id']})
            entry_kind = data.get('kind', 'state')
            if entry_kind not in ('state', 'event'):
                raise Invalid('Выберите утверждение состояния или событие.')
            entry = {'id': uid(), 'text': d['text'], 'kind': entry_kind, 'retracts': [], 'assertions': [], 'thoughtId': d['id']}
            for e in d['config']['edges']:
                if e['included']:
                    entry['assertions'].append({'id': uid(), 'edgeId': e['edgeId'], 'template': copy.deepcopy(e['template']),
                                               'from': mapping[e['from']], 'to': mapping[e['to']], 'slot': '',
                                               'activation': e['activation'], 'localId': e['id'], 'thoughtId': d['id']})
            scene['entries'].append(entry)
            d.update(status='complete', sceneId=scene['id'], entryId=entry['id'], completedRevision=revision,
                     objectBindings=[{'localId': k, 'objectId': v} for k, v in mapping.items()])
            result.update(sceneId=scene['id'], entryId=entry['id'])
    else:
        raise Invalid('Неизвестная операция разбора.')
    return result, action + ': ' + str(data.get('draftId', data.get('nodeId', 'операторская запись')))


def merge(existing, incoming):
    result = copy.deepcopy(existing or empty())
    for key in ('drafts', 'templates', 'candidates'):
        indexed = {v['id']: v for v in result[key]}
        for value in incoming[key]:
            if value['id'] in indexed and indexed[value['id']] != value:
                raise Invalid('Конфликт ID разбора/шаблона/гипотезы; автоматической замены нет.')
            if value['id'] not in indexed:
                result[key].append(copy.deepcopy(value))
    if result['currentDraftId'] is None:
        result['currentDraftId'] = incoming['currentDraftId']
    return result
