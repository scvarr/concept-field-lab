"""Geometry-only actions in the permanent journal; no additional graph fields."""
import json
import math
from app.geometry import points
from app.store import Invalid, Conflict, lookup, clean


def radii(state):
    degree = dict.fromkeys((n['id'] for n in state['nodes']), 0)
    for edge in state['edges']:
        for ident in {edge['from'], edge['to']}:
            degree[ident] += 1
    return {ident: min(26, 8 + 3 * math.sqrt(count)) for ident, count in degree.items()}


def operate(state, action, data, db, revision):
    nodes = {n['id']: n for n in state['nodes']}
    if action == 'layout_pin':
        ids, pinned = data.get('nodeIds'), data.get('pinned')
        if not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids) or len(ids) != len(set(ids)) or not isinstance(pinned, bool):
            raise Invalid('Выберите ID узлов и признак закрепления.')
        for ident in ids:
            node = lookup(state['nodes'], ident, 'узел')
            if pinned:
                node['layoutPinned'] = True
            else:
                node.pop('layoutPinned', None)
        return {'count': len(ids)}, 'Изменено закрепление узлов для раскладки'
    if data.get('confirmed') is not True:
        raise Invalid('Просмотрите и подтвердите изменение расположения.')
    if action == 'layout_restore':
        record = None
        for row in db.execute('SELECT action,detail FROM permanent_revisions ORDER BY id DESC'):
            if row['action'] in ('layout_restore', 'restore', 'import'):
                break
            if row['action'] == 'layout_apply':
                record = json.loads(row['detail'])['layout']
                break
        if not record:
            raise Invalid('Нет доступной последней раскладки; прежние версии сохранены в истории.')
        if any(ident not in nodes or nodes[ident].get('layoutPinned') or {k: nodes[ident][k] for k in ('x', 'y')} != p for ident, p in record['after'].items()):
            raise Invalid('После раскладки позиции/закрепление изменились; используйте историю или новую раскладку.')
        positions = record['before']
        detail = 'Возвращены позиции перед последней раскладкой; структура сохранена'
    else:
        if data.get('previewRevision') != revision:
            raise Conflict('Предпросмотр устарел. Рассчитайте раскладку заново.')
        positions = data.get('positions')
        points(positions)
        if len(positions) > 10000:
            raise Invalid('Предел раскладки — 10 000 перемещаемых узлов.')
        if any(ident not in nodes or nodes[ident].get('layoutPinned') for ident in positions):
            raise Invalid('Раскладка содержит отсутствующий или закреплённый ID.')
        radius = radii(state)
        grid = {}
        for ident, n in nodes.items():
            p = positions.get(ident, n)
            grid.setdefault((math.floor(p['x']/60), math.floor(p['y']/60)), []).append((ident, p))
        for ident, p in positions.items():
            x, y = math.floor(p['x']/60), math.floor(p['y']/60)
            for gx in range(x-1, x+2):
                for gy in range(y-1, y+2):
                    for other, q in grid.get((gx, gy), []):
                        if other != ident and math.hypot(p['x']-q['x'], p['y']-q['y']) < radius[ident]+radius[other]:
                            raise Invalid('Новое расположение накладывает окружности. Пересмотрите область/закрепление.')
        algorithm = clean(data.get('algorithm'), 'алгоритм', True, 100)
        if algorithm not in ('force', 'hierarchical', 'radial'):
            raise Invalid('Неизвестный режим раскладки постоянного графа.')
        record = {'before': {ident: {k: nodes[ident][k] for k in ('x', 'y')} for ident in positions}, 'after': positions, 'algorithm': algorithm}
        detail = json.dumps({'message': 'Применена раскладка постоянного графа', 'layout': record}, ensure_ascii=False)
    for ident, p in positions.items():
        nodes[ident].update(p)
    return {'count': len(positions)}, detail
