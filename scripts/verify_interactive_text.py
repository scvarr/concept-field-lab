"""Read-only audit of M021's manually authored GUI export; no fixture mutation."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
from app.permanent import parse_document


def audit(path):
    raw = Path(path).read_bytes()
    state = parse_document(json.loads(raw))
    checks = []

    def check(condition, description):
        if not condition:
            raise AssertionError(description)
        checks.append(description)

    drafts = state['thoughtLab']['drafts']
    complete = {d['text']: d for d in drafts if d['status'] == 'complete'}
    first = complete['Винт упал на пол']
    repeated = complete['Винт']
    definitions = [complete[t] for t in ('Винт — деталь', 'Винт — крепёж')]
    scenes = state['sceneLab']['scenes']
    dynamic = next(s for s in scenes if s['id'] == first['sceneId'])
    knowledge = next(s for s in scenes if s['label'] == 'Словарь')
    aliases = {n.get('operatorAlias'): n['id'] for n in state['nodes']}
    check(len(state['nodes']) == 8 and len(state['edges']) == 7, '8 постоянных концептов и 7 обычных рёбер.')
    check(not state['designations'] and all(n['label'] == '' for n in state['nodes']), 'Alias не стал словарным обозначением; новые концепты безымянны.')
    check(all(n['structure'] == 'concept' for n in state['nodes']), 'Нет новых α для операторских конструкций.')
    check(not state['definitionDrafts'] and not state['definitionPublications'], 'Нет технического владельца определения.')
    check(len(first['config']['nodes']) == 6 and len(first['config']['edges']) == 5, 'Три позиции, три содержательных концепта, пять явных использований отношений.')
    for start, end, role in [(0, 4, 'Объект'), (5, 9, 'Процесс'), (10, 16, 'XXX')]:
        local = next(n for n in first['config']['nodes'] if n['conceptId'] == aliases[role])
        check(any(a['id'] == local['id'] and a['start'] == start and a['end'] == end for a in first['anchors']), f'Исходный диапазон {start}:{end} связан с позицией {role}.')
    screw = next(n for n in first['config']['nodes'] if n['conceptId'] == aliases['Винт'])
    original_object = next(b['objectId'] for b in first['objectBindings'] if b['localId'] == screw['id'])
    check(repeated['objectBindings'][0]['objectId'] == original_object, 'Повторное упоминание адресует прежний сценический экземпляр винта.')
    check(len(knowledge['entries']) == 2 and knowledge['kind'] == 'knowledge', 'Два определения в обычной сцене знаний, без дубля первого включения.')
    check(all(e['kind'] == 'state' for e in knowledge['entries']), 'Определения сохранены как state, без принудительного event.')
    check(dynamic['entries'][0]['kind'] == 'event', 'Событие падения выбрано оператором явно.')
    check(state['sceneLab']['currentSceneId'] == dynamic['id'] and not dynamic['links'], 'Включение в знания не сменило динамическую сцену или контекст.')
    check(not state['sceneLab']['workspaces'], 'Сохранение знаний не создало извлечений или активации.')
    check(not {o['id'] for o in dynamic['objects']} & {o['id'] for o in knowledge['objects']}, 'Локальные ID разных сцен независимы.')
    for draft in definitions:
        entry = next(e for e in knowledge['entries'] if e['thoughtId'] == draft['id'])
        check(entry['sourceSceneId'] == dynamic['id'] and entry['sourceEntryId'] == draft['entryId'], 'Копия сохраняет адрес исходной сцены и входа: ' + draft['text'])
        check(any(n['conceptId'] == aliases['Винт'] for n in draft['config']['nodes']), 'Определение повторно использует постоянный концепт винта: ' + draft['text'])
        source = {b['localId']: b['objectId'] for b in draft['objectBindings']}
        copied = [o for o in knowledge['objects'] if o.get('thoughtId') == draft['id']]
        check({o['sourceObjectId'] for o in copied} == set(source.values()), 'Сохранено происхождение всех локальных экземпляров: ' + draft['text'])
    check(len(drafts) == 5 and sum(d['status'] == 'draft' for d in drafts) == 1, 'Неудачная первая GUI-проба сохранена отдельным незавершённым черновиком.')
    return {'result': 'passed', 'python': platform.python_version(), 'sha256': hashlib.sha256(raw).hexdigest(), 'checks': checks}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = audit(args.path)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"M021: {len(result['checks'])} checks passed")
