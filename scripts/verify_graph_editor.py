"""Audit committed M018 evidence without a browser or mutable user database."""
import hashlib
import json
import platform
import sqlite3
from pathlib import Path
from app.permanent import parse_document, validate_graph
from app.journal import expand_history


def verify(directory):
    checks = []
    def check(condition, text):
        if not condition:
            raise AssertionError(text)
        checks.append(text)
    def load(file):
        return json.loads((directory / file).read_text(encoding='utf-8'))
    before = parse_document(load('fixture.json'))
    converted = load('conversion.json')
    validate_graph(converted)
    document = load('permanent.json')
    after = parse_document(document)
    reexport = load('reexport.json')
    check(parse_document(reexport) == after, 'Точный state после GUI импорта и повторного экспорта')
    check(any(d['history'] == document['history'] for d in reexport['importedHistory']), 'Полная исходная история сохранена в архиве импорта')
    nodes_before = {n['id']: n for n in before['nodes']}
    nodes = {n['id']: n for n in converted['nodes']}
    check(set(nodes) == set(nodes_before) - {'detail'}, 'Удалён только исходный концепт; новых концептов при преобразовании нет')
    check(nodes['part']['id'] == nodes_before['part']['id'], 'Структура использует прежний ID части')
    for ident in set(nodes) - {'part'}:
        check(nodes[ident] == nodes_before[ident], 'Полный объект сохранён: ' + ident)
    edges_before = {e['id']: e for e in before['edges']}
    edges = {e['id']: e for e in converted['edges']}
    check(set(edges_before) <= set(edges), 'Все исходные edge IDs сохранены')
    for ident, edge in edges_before.items():
        expected = {**edge, 'from': 'part' if edge['from'] == 'detail' else edge['from'],
                    'to': 'part' if edge['to'] == 'detail' else edge['to']}
        check(edges[ident] == expected, 'Только выбранные endpoints изменены, metadata/role/ID сохранены: ' + ident)
    added = [e for i, e in edges.items() if i not in edges_before]
    check(len(added) == 2 and {(e['from'], e['to'], e['role']) for e in added} == {('part', 'mechanism', 'relation'), ('part', 'elementary', 'relation')}, 'Добавлены только два явно построенных отношения структуры')
    check(converted['contextEdges'] == before['contextEdges'], 'Полные контекстные пары и их ID сохранены при преобразовании')
    words = {d['id']: d for d in converted['designations']}
    check(set(words) == {d['id'] for d in before['designations']}, 'Состав словаря без потерь или новых обозначений')
    for word in before['designations']:
        check(words[word['id']] == {**word, 'target': 'part' if word['target'] == 'detail' else word['target']}, 'Сохранены ID/источник обозначения: ' + word['id'])
    for ident, p in converted['definitionPublications'].items():
        check('detail' not in p['nodeIds'], 'Индекс определения без удалённого ID: ' + ident)
    check({e['id'] for e in after['edges']} == set(edges), 'Последующие явные create/delete не оставили лишних отношений')
    check(len(after['nodes']) == 6 and len(after['edges']) == 7 and len(after['contextEdges']) == 2, 'Итоговые размеры канонического графа 6/7/2')
    check(any(d.get('graphStale') and any(n.get('notes') == 'Незавершённая локальная правка' for n in d['nodes']) for d in after['definitionDrafts']), 'Незавершённый конфликтный черновик сохранён')
    check(any(n.get('notes') == 'После preview' for n in after['nodes']), 'Устаревший preview не перезаписал свежую общую правку')
    check(any(n['id'] not in {v['id'] for v in after['nodes']} and n.get('structure') == 'alpha' for d in after['definitionDrafts'] for n in d['nodes']), 'Неполная α существует только в черновике')
    history = list(expand_history(document))
    check(history[-1]['state'] == after, 'Последняя запись журнала совпадает с экспортированным state')
    check(any(r['action'] == 'graph_apply' for r in history), 'Общие правки записаны в историю')
    for row in history:
        validate_graph(row['state'])
    check(True, 'Все snapshots истории проходят структурную валидацию')
    report = load('report.json')
    check(report['ok'] and not report['errors'] and len(report['negative']) >= 7, 'Браузерный сценарий и отрицательные проверки завершены без JS ошибок')
    return {'ok': True, 'checks': checks, 'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
            'historyRows': len(history), 'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(directory.iterdir()) if p.is_file() and p.name != 'verification.json'}}


if __name__ == '__main__':
    import sys
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('docs/manual/evidence/graph-editor')
    result = verify(directory)
    (directory / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'ok': result['ok'], 'checks': len(result['checks']), 'historyRows': result['historyRows']}, ensure_ascii=False))
