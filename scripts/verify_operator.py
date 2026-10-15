"""Audit M020 GUI output and its journal. Reads no SQLite and supplies no scaffold."""
import argparse
import hashlib
import json
import platform
import sqlite3
from pathlib import Path
from app.permanent import parse_document
from app.journal import expand_history


def audit(path):
    raw = Path(path).read_bytes()
    doc = json.loads(raw)
    state = parse_document(doc)
    checks = []

    def check(condition, text):
        if not condition:
            raise AssertionError(text)
        checks.append(text)

    check(doc['version'] == 5 and state['operatorVersion'] == 5, 'Формат v5 и вся цепочка истории проходят валидацию.')
    check(not state['definitionDrafts'] and not state['definitionPublications'], 'Ручная работа не создала определений или технических черновиков.')
    check(all('definitionId' not in v and v.get('origins') for k in ('nodes', 'edges', 'contextEdges', 'designations') for v in state[k]), 'Происхождение постоянных объектов независимо от определения.')
    check(len(state['nodes']) == 12 and len(state['edges']) == 12 and len(state['contextEdges']) == 1, 'После восстановления: 12 концептов / 12 обычных рёбер / 1 контекст.')
    check(all(n['structure'] == 'concept' for n in state['nodes']), 'Нет α или узла классификации операторского шаблона.')
    aliases = {n.get('operatorAlias'): n['id'] for n in state['nodes'] if n.get('operatorAlias')}
    words = {d['text']: d['target'] for d in state['designations']}
    check(not set(aliases.values()) & set(words.values()), 'Рабочие alias не стали словарными обозначениями.')
    drafts = {d['text']: d for d in state['thoughtLab']['drafts']}
    first, second, short, strike, incomplete, rolling = [drafts[t] for t in (
        'Винт упал на пол', 'Гайка упала на землю', 'Винт упал', 'Человек ударил человека', 'Человек ударил', 'Затем винт покатился')]
    check(len(drafts) == 6 and len(state['thoughtLab']['templates']) == 2, '6 разборов и 2 вспомогательных конструкции, не классы графа.')
    check(first['templateRef']['id'] == second['templateRef']['id'] == short['templateRef']['id'], 'Гайка и короткий ввод повторно используют выбранную конструкцию.')
    check(incomplete['status'] == 'draft' and incomplete['templateRef']['id'] == strike['templateRef']['id'] != first['templateRef']['id'], 'Неполный ввод остаётся на трёхкомпонентном шаблоне.')
    complete = [d for d in drafts.values() if d['status'] == 'complete']
    check(len(complete) == 5 and all(d['representation']['confirmed'] for d in complete), 'Пять завершённых мыслей имеют отдельное подтверждение содержания.')
    check(all(d['anchors'] for d in complete), 'Все завершённые вводы сохраняют текстовые соответствия.')
    obj, process = aliases['Объект'], aliases['Процесс']
    short_nodes = {n['id']: n for n in short['config']['nodes']}
    binding = next(e for e in short['config']['edges'] if e['included'] and e['template']['from'] == obj and e['template']['to'] == words['Винт'])
    check(binding['id'] in short_nodes[binding['from']]['contentEdges'] and short_nodes[binding['from']]['bindingRequired'], 'Короткий ввод сохранил подтверждённую предметную связь Объект → Винт.')
    xxx = next(n['conceptId'] for n in first['config']['nodes'] if n['conceptId'] not in (obj, process, words['Винт'], words['Падение'], words['Пол']))
    check(xxx not in words.values() and any(n['conceptId'] == xxx and n['included'] for n in second['config']['nodes']), 'Безымянный XXX повторно использован без назначения смысла.')
    check(not any(n['conceptId'] == xxx and n['included'] for n in short['config']['nodes']), 'XXX остаётся необязательным для короткой мысли.')

    def instance(draft, concept):
        local = next(n['id'] for n in draft['config']['nodes'] if n['conceptId'] == concept and n['included'])
        return next(b['objectId'] for b in draft['objectBindings'] if b['localId'] == local)

    check(instance(first, obj) == instance(rolling, obj), 'Падение и качение используют один подтверждённый сценический ID винта.')
    check(instance(first, process) != instance(rolling, process), 'Процессы падения и качения имеют независимые ID.')
    check(instance(first, obj) != instance(second, obj), 'Выбор общего концепта во втором вводе не объединил винт и гайку.')
    check(any(n.get('sceneObjectId') == instance(first, obj) for n in rolling['config']['nodes']), 'Решение о тождестве явно сохранено в разборе качения.')
    scene = state['sceneLab']['scenes'][0]
    check(len([e for e in scene['entries'] if e.get('thoughtId')]) == 5, 'Неполный ввод не добавлен как сценический факт.')
    check(len(state['sceneLab']['scenes']) == 2 and any(e['kind'] == 'context' for e in scene['entries']), 'Динамическая сцена имеет отдельную явную ссылку контекста на сцену знаний.')
    people = [b['objectId'] for b in strike['objectBindings'] if next(n for n in strike['config']['nodes'] if n['id'] == b['localId'])['conceptId'] == words['Человек']]
    check(len(people) == 2 and people[0] != people[1], 'Два участия одного Человека остаются независимыми.')
    check(len(state['thoughtLab']['candidates']) == 1 and state['thoughtLab']['candidates'][0]['status'] == 'rejected', 'Гипотеза отклонена без добавления контекстного разрешения.')
    history = list(expand_history(doc))
    changes = [r for r in history if r['action'] == 'manage_apply']
    check(bool(changes), 'Журнал содержит реальные массовые удаления GUI.')
    check(any(not r['state']['nodes'] and not r['state']['definitionDrafts'] and 'thoughtLab' not in r['state'] for r in changes), 'В истории есть подтверждённый полный сброс до пустого состояния.')
    check(any(r['action'] == 'graph_apply' and len(r['state']['nodes']) == 1 for r in history), 'После сброса оператор создал новую постоянную структуру.')
    check(history[-1]['state'] == state and any(r['action'] == 'restore' for r in history), 'Восстановление возвращает полный прежний снимок, сохраняя более позднюю историю.')
    check(any(any(d.get('templateArchive') for d in r['state'].get('thoughtLab', {}).get('drafts', [])) for r in changes), 'Удаление шаблона сохранило его снимки в прежних применениях.')
    check(any('sceneLab' in r['state'] and not r['state']['sceneLab']['scenes'] for r in changes), 'Удаление сцены отражено в сохранённом состоянии.')
    return {'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'python': platform.python_version(),
            'sqlite': sqlite3.sqlite_version, 'checks': checks, 'count': len(checks),
            'limits': 'Проверены операторские решения, целостность и изоляция. Смысл связей и тождество предметов устанавливает человек; NLP и новые исследовательские механизмы отсутствуют.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('export')
    p.add_argument('--out')
    args = p.parse_args()
    text = json.dumps(audit(args.export), ensure_ascii=False, indent=2) + '\n'
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    else:
        print(text)
