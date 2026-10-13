"""Operator-edited lexical entry points, independent of conceptual structure."""
import copy
from app.store import Invalid, clean, lookup, uid


def validate_designation(value):
    if not isinstance(value, dict):
        raise Invalid('Ожидалось словарное соответствие.')
    clean(value.get('id'), 'ID обозначения', True, 200)
    clean(value.get('text'), 'обозначение', True, 1000)
    clean(value.get('notes', ''), 'примечание')
    source = value.get('lexicalSource')
    if source is not None:
        if not isinstance(source, dict):
            raise Invalid('Неверный источник словарного значения.')
        clean(source.get('name'), 'источник значения', True, 1000)
        for key in ('lemma', 'entry', 'senseId', 'url', 'revisionUrl', 'retrievedAt', 'license', 'licenseUrl', 'attribution', 'responseSha256', 'transformation', 'originalText'):
            if key in source:
                clean(source[key], key, False, 50000 if key == 'originalText' else 2000)
        if 'revision' in source and (isinstance(source['revision'], bool) or not isinstance(source['revision'], (str, int))):
            raise Invalid('Редакция должна быть строкой или целым числом.')
        if 'revision' in source:
            clean(str(source['revision']), 'редакция', False, 200)


def operate(state, action, data):
    if action == 'designation_remove':
        value = lookup(state['designations'], data.get('designationId'), 'обозначение')
        state['designations'].remove(value)
        return {'designationId': value['id'], 'nodeId': value['target']}, 'Удалено внешнее обозначение; концепт и рёбра сохранены'
    node = lookup(state['nodes'], data.get('nodeId'), 'концепт')
    ident = data.get('designationId')
    previous = lookup(state['designations'], ident, 'обозначение') if ident else None
    if previous and previous['target'] != node['id']:
        raise Invalid('Соответствие принадлежит другому ID. Создайте отдельное обозначение.')
    value = {**copy.deepcopy(previous or {}), 'id': ident or uid(), 'target': node['id'],
             'text': clean(data.get('text'), 'обозначение', True, 1000),
             'notes': clean(data.get('notes', ''), 'примечание'),
             'lexicalSource': copy.deepcopy(data.get('lexicalSource'))}
    if not previous:
        value.update(definitionId=node['definitionId'], source='Ручное соответствие точки входа', origins=copy.deepcopy(node['origins']))
    validate_designation(value)
    if previous:
        previous.clear()
        previous.update(value)
    else:
        state['designations'].append(value)
    return {'designationId': value['id'], 'nodeId': node['id']}, 'Сохранено внешнее обозначение точки входа'
