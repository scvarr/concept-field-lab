"""Validation and numbering for one scene element and its explicit ordinary binding use."""
from app.store import Invalid


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
