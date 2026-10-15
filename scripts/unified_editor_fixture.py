"""Small synthetic operator fixture; relations test editing, not semantic truth."""
import copy
import json
import sys
from pathlib import Path
from app.permanent import PermanentStore


def populate(store):
    def call(action, **data):
        return store.mutate(action, data, store.read()['revision'])
    def node(ident, text, alpha=False):
        return {'id': ident, 'existing': False, 'designation': text,
                'designations': [{'id': 'word-' + ident, 'text': text}],
                'structure': 'alpha' if alpha else 'concept',
                **dict(zip(('x', 'y'), {'detail': (0, 0), 'metal': (320, 0), 'part': (0, 350), 'mechanism': (320, 250), 'elementary': (320, 450), 'screw': (-320, -180), 'nut': (-320, 180)}[ident]))}
    def reuse(ident):
        n = next(n for n in store.read()['state']['nodes'] if n['id'] == ident)
        return {'id': ident, 'existing': True, 'base': copy.deepcopy(n)}
    def edge(ident, source, target, role='relation'):
        return {'id': ident, 'from': source, 'to': target, 'role': role, 'existing': False}
    def publish(ident, title, text, nodes, edges, contexts=None):
        draft = {'id': ident, 'title': title, 'definition': text, 'nodes': nodes, 'edges': edges,
                 'contextEdges': contexts or [], 'routes': []}
        call('definition_save', draft=draft)
        call('definition_publish', draftId=ident, confirmed=True)
    publish('definition-detail', 'Деталь', 'Деталь — элементарная составная часть более сложного механизма или сооружения.',
            [node('detail', 'деталь'), node('metal', 'металл')], [edge('detail-metal', 'detail', 'metal')])
    publish('definition-part', 'Часть', 'Существующие ID для операторской проверки, без автоматического анализа текста.',
            [node('part', 'часть'), node('mechanism', 'механизм'), node('elementary', 'элементарный')], [])
    publish('definition-screw', 'Винт', 'Синтетическая структура винта с общим ID детали.',
            [node('screw', 'винт', True), reuse('detail')],
            [edge('screw-detail-component', 'screw', 'detail', 'component'), edge('screw-detail', 'screw', 'detail')])
    publish('definition-nut', 'Гайка', 'Синтетическая структура гайки с тем же общим ID детали.',
            [node('nut', 'гайка', True), reuse('detail'), reuse('screw'), reuse('metal')],
            [edge('nut-detail-component', 'nut', 'detail', 'component'), edge('nut-detail', 'nut', 'detail'),
             {'id': 'screw-detail', 'from': 'screw', 'to': 'detail', 'existing': True},
             {'id': 'detail-metal', 'from': 'detail', 'to': 'metal', 'existing': True}],
            [{'id': 'context-cross', 'from': 'screw-detail', 'to': 'nut-detail'},
             {'id': 'context-metal', 'from': 'nut-detail', 'to': 'detail-metal'}])
    return store.read()


if __name__ == '__main__':
    store = PermanentStore(sys.argv[1])
    populate(store)
    Path(sys.argv[2]).write_text(json.dumps(store.export(), ensure_ascii=False, indent=2), encoding='utf-8')
