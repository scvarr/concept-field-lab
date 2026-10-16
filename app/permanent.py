from contextlib import closing, contextmanager
"""Canonical graph and transactional SQLite revision journal."""
import copy
import hashlib
import json
import math
import sqlite3
import threading
from pathlib import Path
from app.store import Invalid, Conflict, clean, lookup, uid, now, encode, decode, fields

FORMAT = 'concept-field-permanent'
VERSION = 7
COLLECTIONS = ('nodes', 'edges', 'designations', 'contextEdges')


def empty_graph():
    return {k: [] for k in COLLECTIONS}


def validate_graph(graph):
    if not isinstance(graph, dict) or set(graph) - {'sceneLab', 'thoughtLab', 'operatorVersion'} != set(empty_graph()) or any(not isinstance(graph[k], list) for k in COLLECTIONS):
        raise Invalid('Ожидался один постоянный граф актуального формата.')
    if 'operatorVersion' in graph and (type(graph['operatorVersion']) is not int or graph['operatorVersion'] != 5):
        raise Invalid('Неверная версия операторского состояния.')
    if graph.get('operatorVersion') != 5 and any(
            'representation' in d or 'objectBindings' in d
            or any('sceneObjectId' in n or 'bindingRequired' in n for n in d['config']['nodes'])
            for d in graph.get('thoughtLab', {}).get('drafts', []) + graph.get('thoughtLab', {}).get('templates', [])):
        raise Invalid('Проверка содержания и идентичность экземпляров требуют операторского состояния v5.')
    identities = set()
    def identity(item):
        if not isinstance(item, dict):
            raise Invalid('Ожидался объект графа.')
        ident = clean(item.get('id'), 'ID', True, 200)
        if ident in identities:
            raise Invalid('ID узлов, рёбер, обозначений, контекста должны различаться.')
        identities.add(ident)
    nodes = {n.get('id') for n in graph['nodes'] if isinstance(n, dict)}
    for n in graph['nodes']:
        identity(n)
        if 'operatorRole' in n and type(n['operatorRole']) is not bool:
            raise Invalid('Назначение элемента конструкции задаётся оператором явно.')
        fields(n)
        if n.get('structure') not in ('concept', 'alpha') or n.get('designationOnly') is not True or n.get('label') != '':
            raise Invalid('Новый концепт адресуется по ID и внешним обозначениям, без переноса исторической модели.')
        if not isinstance(n.get('origins'), list):
            raise Invalid('Неверное происхождение концепта.')
        if 'operatorAlias' in n:
            clean(n['operatorAlias'], 'рабочий alias', False, 1000)
        if 'layoutPinned' in n and n['layoutPinned'] is not True:
            raise Invalid('Закрепление layoutPinned должно быть true либо отсутствовать.')
        for k in ('x', 'y'):
            if not isinstance(n.get(k), (int, float)) or isinstance(n[k], bool) or not math.isfinite(n[k]) or abs(n[k]) > 100000:
                raise Invalid('Координаты графа должны быть конечными числами ±100000.')
    for e in graph['edges']:
        identity(e)
        if e.get('from') not in nodes or e.get('to') not in nodes or e.get('role') not in ('relation', 'component'):
            raise Invalid('Обычное ребро требует два концептуальных ID этого графа.')
        clean(e.get('type', ''), 'тип', False, 1000)
    for d in graph['designations']:
        identity(d)
        from app.designations import validate_designation
        validate_designation(d)
        if d.get('target') not in nodes:
            raise Invalid('Обозначение требует существующий концепт.')
    from app.alpha import validate_structure
    validate_structure(graph['nodes'], graph['edges'])
    pairs = set()
    relations = {e['id'] for e in graph['edges'] if e['role'] == 'relation'}
    for context in graph['contextEdges']:
        identity(context)
        pair = context.get('from'), context.get('to')
        if pair[0] not in relations or pair[1] not in relations or pair[0] == pair[1] or pair in pairs:
            raise Invalid('Контекст требует два различных обычных ребра без повторения направленной пары.')
        pairs.add(pair)
    if 'sceneLab' in graph:
        from app.scenes import validate_lab
        validate_lab(graph)
    if 'thoughtLab' in graph:
        from app.thoughts import validate
        validate(graph)



def parse_document(document):
    if not isinstance(document, dict) or document.get('format') != FORMAT or document.get('version') != VERSION or document.get('kind') != 'graph':
        raise Invalid('Нужен актуальный экспорт concept-field-permanent v7.')
    validate_graph(document.get('state'))
    from app.journal import expand_history
    latest = None
    for row in expand_history(document):
        validate_graph(row['state'])
        latest = row['state']
    if latest is not None and latest != document['state']:
        raise Invalid('Последняя строка истории не совпадает с графом.')
    archives = document.get('importedHistory', [])
    if not isinstance(archives, list):
        raise Invalid('Архивы импортной истории должны быть списком.')
    for archive in archives:
        if not isinstance(archive, dict) or 'importedHistory' in archive:
            raise Invalid('Вложенные архивы истории не допускаются.')
        parse_document(archive)
    return copy.deepcopy(document['state'])


class PermanentStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        if self.path.exists() and self.path.stat().st_size:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables and 'permanent_revisions' not in tables:
                    raise Invalid('Нужна новая SQLite или база постоянного графа. Старый формат не изменён.')
                if 'permanent_revisions' in tables:
                    row = db.execute('SELECT state FROM permanent_revisions ORDER BY id DESC LIMIT 1').fetchone()
                    if row:
                        validate_graph(decode(row[0]))
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS permanent_revisions (id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, state BLOB NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS permanent_imports (fingerprint TEXT PRIMARY KEY, time TEXT NOT NULL, document BLOB NOT NULL)')
            if not db.execute('SELECT 1 FROM permanent_revisions LIMIT 1').fetchone():
                detail = json.dumps({'message': 'Создан пустой постоянный граф'}, ensure_ascii=False)
                db.execute('INSERT INTO permanent_revisions VALUES (0,?,?,?,?)', (now(), 'init', detail, encode(empty_graph())))
        validate_graph(self.read()['state'])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.connect() as db:
            row = db.execute('SELECT * FROM permanent_revisions ORDER BY id DESC LIMIT 1').fetchone()
            return {'revision': row['id'], 'state': decode(row['state'])}

    def history(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,time,action,detail FROM permanent_revisions ORDER BY id DESC')]

    def export(self):
        from app.journal import compact_with_latest
        with self.lock, self.connect() as db:
            db.execute('BEGIN')
            def snapshots():
                for raw in db.execute('SELECT * FROM permanent_revisions ORDER BY id'):
                    row = dict(raw)
                    row['state'] = decode(row['state'])
                    yield row
            history, state = compact_with_latest(snapshots())
            archives = [decode(r[0]) for r in db.execute('SELECT document FROM permanent_imports ORDER BY time,fingerprint')]
        return {'format': FORMAT, 'version': VERSION, 'kind': 'graph', 'exportedAt': now(), 'state': state,
                'historyEncoding': 'rfc6902-chain-v1', 'history': history, **({'importedHistory': archives} if archives else {})}

    def import_preview(self, document):
        incoming = parse_document(document)
        existing = self.read()['state']
        if incoming == existing:
            return {'duplicates': True, 'counts': {k: len(incoming[k]) for k in COLLECTIONS}}
        merged = self.merge_import(existing, incoming)
        return {'duplicates': False, 'additions': {k: len(merged[k]) - len(existing[k]) for k in COLLECTIONS},
                **({'sceneAdditions': {k: len(merged['sceneLab'][k]) - len(existing.get('sceneLab', {}).get(k, []))
                                       for k in ('scenes', 'workspaces')}} if 'sceneLab' in merged else {})}

    @staticmethod
    def merge_import(existing, incoming):
        result = copy.deepcopy(existing)
        if 'operatorVersion' in incoming:
            result['operatorVersion'] = incoming['operatorVersion']
        # Import adds exact IDs; conflicts never silently replace existing operators' work.
        for key in COLLECTIONS:
            indexed = {v['id']: v for v in result[key]}
            for item in incoming[key]:
                if item['id'] in indexed:
                    if indexed[item['id']] != item:
                        raise Invalid(f'Импорт конфликтует с существующим ID {item["id"]}; автоматической замены нет.')
                else:
                    result[key].append(copy.deepcopy(item))
        if 'sceneLab' in incoming:
            from app.scenes import merge_lab
            result['sceneLab'] = merge_lab(result.get('sceneLab'), incoming['sceneLab'])
        if 'thoughtLab' in incoming:
            from app.thoughts import merge
            result['thoughtLab'] = merge(result.get('thoughtLab'), incoming['thoughtLab'])
        validate_graph(result)
        return result

    def mutate(self, action, data, revision):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM permanent_revisions ORDER BY id DESC LIMIT 1').fetchone()
            if revision != row['id']:
                raise Conflict('Граф изменился в другой вкладке. Обновите страницу и повторите действие.')
            state = decode(row['state'])
            result, detail = {}, action
            if action == 'manage_apply':
                from app.lifecycle import prepare
                if data.get('confirmed') is not True or data.get('previewRevision') != row['id']:
                    raise Invalid('Нужны актуальный preview и явное подтверждение удаления.')
                state, result = prepare(state, data, row['id'])
                if result['blocked'] or result['hash'] != data.get('previewHash'):
                    raise Invalid('Состав удаления изменён или остались зависимости; получите новый preview.')
                detail = json.dumps(result, ensure_ascii=False)
            elif isinstance(action, str) and action.startswith('thought_'):
                from app.thoughts import operate as thought_operate
                result, detail = thought_operate(state, action, data, row['id'])
            elif isinstance(action, str) and action.startswith('scene_'):
                from app.scenes import operate as scene_operate
                result, detail = scene_operate(state, action, data, row['id'])
            elif action == 'graph_apply':
                if data.get('confirmed') is not True or data.get('previewRevision') != row['id']:
                    raise Invalid('Просмотрите актуальный результат и подтвердите преобразование.')
                from app.graph_editor import prepare
                state, result = prepare(state, data)
                detail = json.dumps({'message': 'Подтверждена атомарная правка общего графа', 'changes': result}, ensure_ascii=False)
            elif action in ('designation_save', 'designation_remove'):
                from app.designations import operate as edit_designation
                result, detail = edit_designation(state, action, data)
            elif action == 'position':
                node = lookup(state['nodes'], data.get('nodeId'), 'концепт')
                node.update(x=data.get('x'), y=data.get('y'))
                detail = 'Изменена позиция концепта'
            elif action in ('layout_apply', 'layout_restore', 'layout_pin'):
                from app.permanent_geometry import operate as geometry
                result, detail = geometry(state, action, data, db, row['id'])
            elif action == 'import':
                if data.get('confirmed') is not True:
                    raise Invalid('Просмотрите и подтвердите импорт.')
                incoming = parse_document(data.get('document'))
                state = self.merge_import(state, incoming)
                original = {k: v for k, v in data['document'].items() if k != 'importedHistory'}
                for document in [original, *data['document'].get('importedHistory', [])]:
                    fingerprint = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    db.execute('INSERT OR IGNORE INTO permanent_imports VALUES (?,?,?)', (fingerprint, now(), encode(document)))
                detail = 'Подтверждён импорт постоянного графа с сохранением ID'
            elif action == 'restore':
                if data.get('confirmed') is not True:
                    raise Invalid('Подтвердите восстановление всего графа.')
                target = db.execute('SELECT state FROM permanent_revisions WHERE id=?', (data.get('targetRevision'),)).fetchone()
                if target is None:
                    raise Invalid('Версия постоянного графа отсутствует.')
                state = decode(target[0])
                detail = f'Восстановлена версия {data["targetRevision"]}; прежняя история сохранена'
            else:
                raise Invalid('В постоянном графе нет операций исследований, источников и отождествления.')
            validate_graph(state)
            if state == decode(row['state']):
                return {'revision': row['id'], 'state': state, 'result': result}
            new_revision = row['id'] + 1
            db.execute('INSERT INTO permanent_revisions VALUES (?,?,?,?,?)', (new_revision, now(), action, detail, encode(state)))
            return {'revision': new_revision, 'state': state, 'result': result}
