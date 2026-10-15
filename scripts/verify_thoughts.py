"""Audit the actual browser export, without opening SQLite or using a fixture."""
import argparse
import hashlib
import json
import platform
import sqlite3
from pathlib import Path
from app.permanent import parse_document


def audit(path):
    raw = Path(path).read_bytes()
    document = json.loads(raw)
    state = parse_document(document)
    checks = []

    def check(value, text):
        if not value:
            raise AssertionError(text)
        checks.append(text)

    lab = state['thoughtLab']
    drafts = {d['text']: d for d in lab['drafts']}
    first, second, short, third, incomplete = [drafts[t] for t in (
        'Винт упал на пол', 'Гайка упала на землю', 'Винт упал', 'Человек ударил человека', 'Человек ударил')]
    aliases = {n.get('operatorAlias'): n['id'] for n in state['nodes'] if n.get('operatorAlias')}
    words = {d['text']: d['target'] for d in state['designations']}
    obj, process, subject = [aliases[k] for k in ('Объект', 'Процесс', 'Субъект')]
    check(document['version'] == 4, 'Экспорт v4 и полная цепочка истории валидны.')
    check(len(state['nodes']) == 11 and len(state['edges']) == 11, '11 постоянных концептов и 11 обычных рёбер создано оператором.')
    check(all(n['structure'] == 'concept' and n['label'] == '' for n in state['nodes']), 'Нет α или постоянного узла для классификации мысли.')
    check(not {obj, process, subject} & set(words.values()), 'Рабочие alias не являются словарными обозначениями.')
    check(len(lab['templates']) == 2, 'Две самостоятельные операторские конструкции.')
    check(first['templateRef']['id'] == second['templateRef']['id'] == short['templateRef']['id'], 'Первые три применения используют одну конструкцию.')
    check(third['templateRef']['id'] == incomplete['templateRef']['id'] != first['templateRef']['id'], 'Для удара выбран другой шаблон, включая неполный ввод.')
    check([d['status'] for d in (first, second, short, third, incomplete)] == ['complete'] * 4 + ['draft'], 'Четыре завершённых мысли и сохранённый незавершённый разбор.')
    check(sum(n['required'] for n in first['contract']['nodes']) == 2 and sum(n['required'] for n in third['contract']['nodes']) == 3, 'Обязательный состав шаблонов: 2 и 3 элемента.')
    for d in (first, second):
        check(all(any(n['conceptId'] == i and n['included'] for n in d['config']['nodes']) for i in (obj, process, words['Падение'])), 'Общие содержательные и безымянные ID повторно используются: ' + d['text'])
    first_unknown = next(n['conceptId'] for n in first['config']['nodes']
                         if n['conceptId'] not in (obj, process, words['Винт'], words['Падение'], words['Пол']))
    check(first_unknown not in words.values(), 'XXX остаётся безымянным концептом без навязанного типа.')
    check(any(n['conceptId'] == first_unknown and n['included'] for n in second['config']['nodes']), 'Второй ввод повторно использует тот же XXX.')
    falling_edges = {e['id'] for e in state['edges'] if e['from'] == process and e['to'] == words['Падение']}
    check(not any(n['conceptId'] == first_unknown and n['included'] for n in short['config']['nodes'])
          and any(e['edgeId'] in falling_edges and e['included'] for e in short['config']['edges']),
          'Короткая мысль завершена без XXX с сохранённым отношением Процесс → Падение.')
    check(all(d['anchors'] for d in (first, second, third)), 'Сохранились соответствия фрагментов и локальных ID.')
    check(any(e['activation'] == 'context' for e in first['config']['edges']) and bool(first['trace']), 'Контекстное исполнение первого разбора имеет отдельную трассу.')
    check(all(e['activation'] == 'direct' for e in second['config']['edges'] if e['included']), 'Второй разбор имеет собственные непосредственные активации.')
    scene = state['sceneLab']['scenes'][0]
    check(len(scene['entries']) == 4, 'Незавершённый ввод не создаёт произошедший сценический вход.')
    local = lambda d: [o for o in scene['objects'] if o.get('thoughtId') == d['id']]
    a, b = local(first), local(second)
    check(not {o['id'] for o in a} & {o['id'] for o in b}, 'Ни один сценический экземпляр первого и второго разборов не разделён.')
    check(next(o['id'] for o in a if o['conceptId'] == process) != next(o['id'] for o in b if o['conceptId'] == process), 'Процессы имеют независимые локальные ID.')
    people = [o for o in local(third) if o['conceptId'] == words['Человек']]
    check(len(people) == 2 and people[0]['id'] != people[1]['id'] and people[0]['label'] != people[1]['label'], 'Один концепт Человек имеет два разных участия и значения.')
    check(any(n['conceptId'] == subject and n['required'] and not n['value'] for n in incomplete['config']['nodes']), 'Незаполненный обязательный Субъект сохранён без подмены конструкции.')
    check(len(state['contextEdges']) == 1 and len(lab['candidates']) == 1 and lab['candidates'][0]['status'] == 'rejected', 'Отклонённая гипотеза не добавила контекстное ребро.')
    # Source references in every thought are checked again independently of validate().
    edges = {e['id']: e for e in state['edges']}
    for d in lab['drafts']:
        nodes = {n['id']: n for n in d['config']['nodes']}
        check(all(all(nodes[e[end]]['conceptId'] == edges[e['edgeId']][end] for end in ('from', 'to')) for e in d['config']['edges']),
              'Локальные концы точно соответствуют постоянным рёбрам: ' + d['text'])
    return {'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'python': platform.python_version(),
            'sqlite': sqlite3.sqlite_version, 'checks': checks, 'count': len(checks),
            'limitation': 'Проверены ручные структуры и операционная изоляция. Семантическая применимость, эквивалентность шаблонов и математические кандидаты не доказаны.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('export')
    parser.add_argument('--out')
    args = parser.parse_args()
    result = json.dumps(audit(args.export), ensure_ascii=False, indent=2) + '\n'
    if args.out:
        Path(args.out).write_text(result, encoding='utf-8')
    else:
        print(result)
