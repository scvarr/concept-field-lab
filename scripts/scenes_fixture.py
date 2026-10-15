"""Synthetic manual A–D scenario. Refuses to overwrite an existing SQLite."""
import argparse
import json
from pathlib import Path
from app.permanent import PermanentStore
from app.scenes import projection


def call(store, action, **data):
    return store.mutate(action, data, store.read()['revision'])['result']


def scaffold(store, with_content=False):
    """Only possible relations; none asserts a fact about a nut/screw."""
    labels = {'item': 'Объект', 'category': 'Категория', 'place': 'Место'}
    if with_content:
        labels.update({'meaning-nut': 'Гайка', 'meaning-detail': 'Деталь', 'meaning-screw': 'Винт'})
    draft = {'id': 'scene-scaffold', 'title': 'Каркас сцен MVP',
             'definition': 'Операторские шаблоны возможных заполнений, без конкретных объектов и фактов.',
             'nodes': [{'id': i, 'existing': False, 'designation': text,
                        'designations': [{'id': 'word-' + i, 'text': text}], 'x': j * 260, 'y': 0}
                       for j, (i, text) in enumerate(labels.items())],
             'edges': [{'id': i, 'from': 'item', 'to': target, 'role': 'relation', 'existing': False,
                        'parallelReason': 'Разные операторские отношения: состояние и событие.'}
                       for i, target in [('classification', 'category'), ('location', 'place'), ('fall', 'place')]],
             'contextEdges': [{'id': 'classification-location', 'from': 'classification', 'to': 'location'}], 'routes': []}
    call(store, 'definition_save', draft=draft)
    call(store, 'definition_publish', draftId=draft['id'], confirmed=True)
    state = store.read()['state']
    operations = [{'op': 'put', 'collection': 'edges',
                   'value': {**next(e for e in state['edges'] if e['id'] == ident), 'type': text}}
                  for ident, text in [('classification', 'является'), ('location', 'лежит на'), ('fall', 'упал на')]]
    call(store, 'graph_apply', operations=operations, confirmed=True, previewRevision=store.read()['revision'])


def populate(store, with_content=False):
    scaffold(store, with_content)
    c = lambda action, **data: call(store, action, **data)
    scene = lambda label, kind='knowledge': c('scene_create', label=label, kind=kind)['sceneId']
    obj = lambda sid, label, concept, content=None: c('scene_object', sceneId=sid, label=label, conceptId=concept,
        **({'contentConceptId': content} if content else {}))['objectId']
    fact = lambda edge, a, b, slot='': {'edgeId': edge, 'from': a, 'to': b, 'slot': slot}
    knowledge = scene('Гайка — деталь')
    nut = obj(knowledge, 'Гайка', 'item', 'meaning-nut' if with_content else None)
    detail = obj(knowledge, 'Деталь', 'category', 'meaning-detail' if with_content else None)
    nut_fact = c('scene_input', sceneId=knowledge, text='Гайка — деталь', kind='state',
                 assertions=[fact('classification', nut, detail)])['assertionIds'][0]
    physics = scene('Физика')
    c('scene_link', sceneId=physics, targetId=knowledge)
    dialogue = scene('Разговор о винте', 'dialogue')
    c('scene_context', sceneId=dialogue, text='Физика')
    screw = obj(dialogue, 'Винт №1', 'item', 'meaning-screw' if with_content else None)
    table, floor = obj(dialogue, 'Стол', 'place'), obj(dialogue, 'Пол', 'place')
    c('scene_input', sceneId=dialogue, text='Винт лежит на столе', kind='state', assertions=[fact('location', screw, table, 'положение')])
    previous = projection(next(s for s in store.read()['state']['sceneLab']['scenes'] if s['id'] == dialogue))[0]['id']
    c('scene_input', sceneId=dialogue, text='Винт упал на пол', kind='event', assertions=[fact('fall', screw, floor)], retracts=[previous])
    c('scene_input', sceneId=dialogue, text='Винт лежит на полу', kind='state', assertions=[fact('location', screw, floor, 'положение')])
    workspace = c('scene_workspace', sceneId=dialogue, label='Селективное извлечение')['workspaceId']
    extracted = c('scene_extract', workspaceId=workspace, sourceSceneId=knowledge, assertionIds=[nut_fact])
    c('scene_seed', workspaceId=workspace, assertionId=extracted['assertionIds'][0])
    c('scene_extract', workspaceId=workspace, sourceSceneId=knowledge, assertionIds=[nut_fact])
    ids = {'knowledge': knowledge, 'physics': physics, 'dialogue': dialogue, 'screw': screw,
           'table': table, 'floor': floor, 'workspace': workspace, 'nutFact': nut_fact, 'detailA': detail}
    if with_content:
        second = scene('Винт — деталь')
        second_screw = obj(second, 'Винт', 'item', 'meaning-screw')
        second_detail = obj(second, 'Та же деталь в B', 'category', 'meaning-detail')
        second_fact = c('scene_input', sceneId=second, text='Винт — деталь', kind='state',
                       assertions=[fact('classification', second_screw, second_detail)])['assertionIds'][0]
        chemistry = scene('Химия')
        c('scene_context', sceneId=dialogue, text='Обсуждаем физику', contextSceneId=physics)
        c('scene_context', sceneId=dialogue, text='Теперь обсуждаем химию', contextSceneId=chemistry)
        ids.update(second=second, detailB=second_detail, secondFact=second_fact, chemistry=chemistry)
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('test-output/scenes-demo/workspace.sqlite3'))
    parser.add_argument('--scaffold-only', action='store_true')
    parser.add_argument('--review', action='store_true', help='Общий содержательный концепт в A/B и смена Физика → Химия')
    args = parser.parse_args()
    if args.db.exists():
        parser.error('База уже существует. Выберите новый путь: существующие базы не изменяются.')
    store = PermanentStore(args.db)
    ids = {} if args.scaffold_only else populate(store, with_content=args.review)
    if args.scaffold_only:
        scaffold(store, with_content=args.review)
    export = args.db.with_suffix('.json')
    export.write_text(json.dumps(store.export(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'database': str(args.db.resolve()), 'export': str(export.resolve()), 'ids': ids}, ensure_ascii=False))


if __name__ == '__main__':
    main()
