"""Independent A–D audit of the browser export; does not open any SQLite."""
import argparse
import hashlib
import json
import platform
import sqlite3
import sys
from pathlib import Path
from app.permanent import parse_document


def audit(path, review=False):
    raw = Path(path).read_bytes()
    document = json.loads(raw)
    state = parse_document(document)
    lab = state['sceneLab']
    checks = []
    def check(value, text):
        if not value:
            raise AssertionError(text)
        checks.append(text)
    def scene(label):
        return next(s for s in lab['scenes'] if s['label'] == label)
    knowledge, physics, dialogue = scene('Гайка — деталь'), scene('Физика'), scene('Разговор')
    check(document['version'] == 3, 'Формат v3 проходит полную валидацию и проверку цепочки истории.')
    check((len(state['nodes']), len(state['edges'])) == (6 if review else 3, 3),
          'Каркас: 6 концептов (3 позиции и 3 содержательных) / 3 возможных отношения.' if review else 'Каркас остался 3 концепта / 3 возможных отношения.')
    if review:
        check(not any(e['from'].startswith('meaning-') or e['to'].startswith('meaning-') for e in state['edges']),
              'Классификации Гайка → Деталь / Винт → Деталь не записаны рёбрами каркаса.')
    else:
        check(not any(d['text'] in ('Гайка', 'Винт №1', 'Стол', 'Пол') for d in state['designations']), 'Обозначения конкретных заполнений отсутствуют в каркасе.')
    check(physics['links'] == [knowledge['id']] and physics['id'] in dialogue['links'], 'Ссылки разговор → Физика → знание сохранены.')
    check(len(knowledge['entries'][0]['assertions']) == 1, 'Знание «Гайка — деталь» сохранено утверждением сцены.')
    three = dialogue['entries'][1:4]
    check([e['text'] for e in three] == ['Винт лежит на столе', 'Винт упал на пол', 'Винт лежит на полу'], 'Три входа сохранены в требуемой последовательности.')
    screw_ids = {f['from'] for e in three for f in e['assertions']}
    check(len(screw_ids) == 1, 'У трёх входов один ID винта.')
    check(three[1]['kind'] == 'event' and three[1]['retracts'] == [three[0]['assertions'][0]['id']], 'Событие содержит отдельное операторское снятие старого положения.')
    # Deliberately independent replay, not a call to the implementation's projection.
    current, prefixes = {}, []
    for entry in dialogue['entries']:
        for ident in entry['retracts']:
            current.pop(ident, None)
        if entry['kind'] == 'state':
            for fact in entry['assertions']:
                if fact['slot']:
                    for ident, previous in list(current.items()):
                        if (previous['from'], previous['slot']) == (fact['from'], fact['slot']):
                            del current[ident]
                current[fact['id']] = fact
        prefixes.append(list(current.values()))
    object_labels = {o['id']: o['label'] for o in dialogue['objects']}
    check(object_labels[prefixes[1][0]['to']] == 'Стол', 'После первого сообщения положение — стол.')
    check(prefixes[2] == [], 'После события новое положение неизвестно; физического вывода нет.')
    check(object_labels[prefixes[3][0]['to']] == 'Пол', 'После третьего сообщения положение — пол.')
    workspace = lab['workspaces'][0]
    a, b, local, *other = workspace['bundles']
    check(a['sourceSceneId'] == b['sourceSceneId'] == knowledge['id'], 'Две первые группы извлечены из одной накопленной сцены.')
    check(a['assertions'][0]['origin']['assertionId'] == b['assertions'][0]['origin']['assertionId'], 'Две копии сохраняют одно происхождение утверждения.')
    check(a['objects'][0]['id'] != b['objects'][0]['id'] and a['assertions'][0]['id'] != b['assertions'][0]['id'], 'Копии объектов и утверждений имеют разные ID.')
    check(len(a['assertions']) == len(b['assertions']) == 1, 'Каждое извлечение знания ограничено выбранным заполнением.')
    steps = [e for e in workspace['trace'] if e['op'] == 'step']
    check(len(steps) == 1 and steps[0]['contextId'] == 'classification-location', 'В трассе один исполненный направленный локальный шаг.')
    check({steps[0]['from'], steps[0]['to']} <= {f['id'] for f in local['assertions']}, 'Шаг не пересекает границу группы копий.')
    check(all(f['activation'] == 'inactive' for bundle in workspace['bundles'] for f in bundle['assertions']), 'Последний ручной reset сбросил локальные состояния, сохранив трассу.')
    if review:
        second, chemistry = scene('Винт — деталь'), scene('Химия')
        fa, fb = knowledge['entries'][0]['assertions'][0], second['entries'][0]['assertions'][0]
        detail_a = next(o for o in knowledge['objects'] if o['id'] == fa['to'])
        detail_b = next(o for o in second['objects'] if o['id'] == fb['to'])
        check(detail_a['id'] != detail_b['id'] and detail_a['label'] != detail_b['label'], 'Объекты детали в A/B имеют разные локальные ID и подписи.')
        check(detail_a['contentConceptId'] == detail_b['contentConceptId'] == 'meaning-detail', 'В A/B повторно используется один устойчивый содержательный концепт meaning-detail.')
        check(any(n['id'] == 'meaning-detail' for n in state['nodes']), 'Общая содержательная ссылка адресует концепт каркаса, не только роль category.')
        check(not knowledge['links'] and not second['links'], 'Сцены A/B независимы: не ссылаются друг на друга.')
        contexts = [e for e in dialogue['entries'] if e['kind'] == 'context']
        check([(e['text'], e['contextSceneId']) for e in contexts[-2:]] == [
            ('Обсуждаем физику', physics['id']), ('Теперь обсуждаем химию', chemistry['id'])],
            'Два входа явно задают Физика → Химия без разбора русского текста.')
        check(contexts[-1]['contextSceneId'] == chemistry['id'] and physics['id'] in dialogue['links'] and chemistry['id'] in dialogue['links'],
              'Действует последний контекст Химия; обе накопленные ссылки сохранены.')
        check(chemistry['entries'] == [] and chemistry['objects'] == [], 'Смена темы не создаёт онтологию или факты Химии.')
        check(len(other) == 1 and other[0]['sourceSceneId'] == second['id'], 'Отдельная группа B не объединена с A или разговором по общему концепту.')
        copy_a = next(o for o in a['objects'] if o.get('contentConceptId') == 'meaning-detail')
        copy_b = next(o for o in other[0]['objects'] if o.get('contentConceptId') == 'meaning-detail')
        roots = [next(n for n in o['structure']['nodes'] if n['id'] == o['structure']['rootId']) for o in (copy_a, copy_b)]
        check(roots[0]['id'] != roots[1]['id'] and roots[0]['sourceId'] == roots[1]['sourceId'] == 'meaning-detail',
              'Рабочие структуры разных сцен имеют новые локальные ID и общее происхождение содержательного концепта.')
    return {'result': 'passed', 'checks': checks, 'sha256': hashlib.sha256(raw).hexdigest(),
            'python': sys.version, 'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
            'counts': {'scenes': len(lab['scenes']), 'workspaces': len(lab['workspaces']),
                       'entries': sum(len(s['entries']) for s in lab['scenes']), 'bundles': len(workspace['bundles'])},
            'scope': 'Структурная проверка синтетического ввода; семантическая истинность/активация общего вида не проверяются.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('report', type=Path, nargs='?')
    parser.add_argument('--review', action='store_true')
    args = parser.parse_args()
    text = json.dumps(audit(args.export, args.review), ensure_ascii=False, indent=2) + '\n'
    if args.report:
        args.report.write_text(text, encoding='utf-8')
    else:
        print(text)
