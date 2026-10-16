"""Storage adapters for one scene element and its explicit ordinary binding use."""
import copy
from app.store import Invalid


def compact_config(config):
    """Migrate only explicit, unambiguous operator bindings; never infer roles."""
    result = copy.deepcopy(config)
    removed = {}
    for node in result['nodes']:
        if node.get('contentConceptId'):
            continue
        uses = [e for e in result['edges'] if e['id'] in node.get('contentEdges', []) and e['from'] == node['id']]
        if not node.get('bindingRequired') or len(uses) != 1:
            continue
        use = uses[0]
        target = next((n for n in result['nodes'] if n['id'] == use['to']), None)
        if not target or target['id'] == node['id'] or target.get('bindingRequired') or target.get('contentConceptId'):
            raise Invalid('Историческая привязка неоднозначна; создайте новую конструкцию вручную.')
        if any(e['id'] != use['id'] and target['id'] in (e['from'], e['to']) for e in result['edges']):
            raise Invalid('Содержательный экземпляр имеет самостоятельные связи; уточните конструкцию вручную.')
        node['contentConceptId'] = target['conceptId']
        removed[target['id']] = node['id']
        use.update(to=node['id'], binding=True)
    result['nodes'] = [n for n in result['nodes'] if n['id'] not in removed]
    if any(not n.get('contentConceptId') for n in result['nodes']):
        raise Invalid('В исторической конструкции не для всех элементов явно задано содержание. Создайте уточнённую конструкцию вручную; оригинал сохранён.')
    return result, removed


def end_concept(obj, use, end):
    if use.get('binding') is True and end == 'to':
        return obj.get('contentConceptId')
    return obj.get('conceptId')


def validate_binding(use, objects):
    if 'binding' in use and type(use['binding']) is not bool:
        raise Invalid('Признак содержательного использования должен быть логическим.')
    if use.get('binding'):
        obj = objects.get(use.get('from'))
        if (not obj or use.get('from') != use.get('to') or not obj.get('contentConceptId')
                or obj['conceptId'] == obj['contentConceptId']):
            raise Invalid('Содержательное ребро связывает структуру и содержание одного элемента.')


def requires_v6(state):
    lab = state.get('thoughtLab', {})
    return (any('operatorRole' in n for n in state['nodes']) or any(
        any('contentConceptId' in n for n in d['config']['nodes'])
        for key in ('drafts', 'templates') for d in lab.get(key, [])))


def assign_numbers(graph, draft, previous):
    scene = next((s for s in graph.get('sceneLab', {}).get('scenes', []) if s['id'] == draft.get('sceneId')), None)
    objects = scene['objects'] if scene else []
    used, object_numbers = {}, {}
    for obj in objects:
        role = obj['conceptId']
        number = obj.get('displayNumber', used.get(role, 0) + 1)
        used[role] = max(used.get(role, 0), number)
        object_numbers[obj['id']] = number
    for other in graph['thoughtLab']['drafts']:
        if other['id'] == draft['id'] or other.get('sceneId') != draft.get('sceneId') or other['status'] != 'draft':
            continue
        for node in other['config']['nodes']:
            if node.get('displayNumber') and node['included']:
                used[node['conceptId']] = max(used.get(node['conceptId'], 0), node['displayNumber'])
    old = {n['id']: n for n in previous}
    for node in draft['config']['nodes']:
        if 'contentConceptId' not in node:
            continue
        former = old.get(node['id'], {})
        number = object_numbers.get(node.get('sceneObjectId'))
        if number is None and former.get('conceptId') == node['conceptId']:
            number = former.get('displayNumber')
        if number is None:
            number = used.get(node['conceptId'], 0) + 1
        node['displayNumber'] = number
        used[node['conceptId']] = max(used.get(node['conceptId'], 0), number)
