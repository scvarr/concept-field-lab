from contextlib import closing
"""One canonical graph in the existing SQLite journal; legacy tables stay intact."""
import copy
import hashlib
import json
import math
import sqlite3
import threading
from pathlib import Path
from app.store import Store, Invalid, Conflict, clean, lookup, uid, now, encode, decode, fields

FORMAT = 'concept-field-permanent'
VERSION = 1
COLLECTIONS = ('nodes', 'edges', 'designations', 'contextEdges')


def empty_graph():
    return {**{k: [] for k in COLLECTIONS}, 'definitionDrafts': [], 'definitionPublications': {}}


def validate_graph(graph):
    from app.builder import validate_extension
    if not isinstance(graph, dict) or set(graph) != set(empty_graph()) or any(not isinstance(graph[k], list) for k in COLLECTIONS):
        raise Invalid('Ожидался один постоянный граф; исторические исследования открываются отдельно.')
    identities = set()
    def identity(item):
        if not isinstance(item, dict):
            raise Invalid('Ожидался объект графа.')
        ident = clean(item.get('id'), 'ID', True, 200)
        if ident in identities:
            raise Invalid('ID узлов, рёбер, обозначений, контекста и определений должны различаться.')
        identities.add(ident)
    nodes = {n.get('id') for n in graph['nodes'] if isinstance(n, dict)}
    for n in graph['nodes']:
        identity(n)
        fields(n)
        if n.get('structure') != 'concept' or n.get('designationOnly') is not True or n.get('label') != '':
            raise Invalid('Новый концепт адресуется по ID и внешним обозначениям, без переноса исторической модели.')
        if not isinstance(n.get('origins'), list):
            raise Invalid('Неверное происхождение концепта.')
        for k in ('x', 'y'):
            if not isinstance(n.get(k), (int, float)) or isinstance(n[k], bool) or not math.isfinite(n[k]) or abs(n[k]) > 100000:
                raise Invalid('Координаты графа должны быть конечными числами ±100000.')
    for e in graph['edges']:
        identity(e)
        if e.get('from') not in nodes or e.get('to') not in nodes or e.get('role') != 'relation':
            raise Invalid('Обычное ребро требует два концептуальных ID этого графа.')
        clean(e.get('type', ''), 'тип', False, 1000)
    for d in graph['designations']:
        identity(d)
        clean(d.get('text'), 'обозначение', True, 1000)
        if d.get('target') not in nodes:
            raise Invalid('Обозначение требует существующий концепт.')
    if any(not any(d['target'] == n for d in graph['designations']) for n in nodes):
        raise Invalid('Концепт должен иметь внешнее обозначение.')
    validate_extension(graph, identity)


def logical_digest(db):
    digest = hashlib.sha256()
    for line in db.iterdump():
        digest.update(line.encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


def verified_backup(path):
    """SQLite backup includes WAL; verify the very same read snapshot before writes."""
    path = Path(path).resolve()
    directory = path.parent / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f'{path.stem}-legacy-{uid()}.sqlite3'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('BEGIN')
        source.execute('SELECT name FROM sqlite_master').fetchall()
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise Invalid('Резервная SQLite не прошла проверку целостности; переход остановлен.')
            original_digest = logical_digest(source)
            if original_digest != logical_digest(destination):
                raise Invalid('Резервная SQLite отличается от исходного снимка; переход остановлен.')
    manifest = {'sourcePath': str(path), 'backupPath': str(target), 'createdAt': now(),
        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'logicalSha256': original_digest,
        'integrity': 'ok', 'method': 'sqlite3.Connection.backup from an open read transaction (including WAL)'}
    target.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return manifest


def parse_document(document):
    if not isinstance(document, dict) or document.get('format') != FORMAT or document.get('version') != VERSION or document.get('kind') != 'graph':
        raise Invalid('Нужен экспорт concept-field-permanent v1. Старые графы не переносятся автоматически: откройте их в историческом режиме.')
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


class PermanentStore(Store):
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        backup = None
        if self.path.exists() and self.path.stat().st_size:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'permanent_revisions' not in tables:
                if tables and 'revisions' not in tables:
                    raise Invalid('Эта SQLite не является базой приложения; файл оставлен без изменения.')
                if 'revisions' in tables:
                    backup = verified_backup(self.path)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS permanent_revisions (id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, state BLOB NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS permanent_imports (fingerprint TEXT PRIMARY KEY, time TEXT NOT NULL, document BLOB NOT NULL)')
            if not db.execute('SELECT 1 FROM permanent_revisions LIMIT 1').fetchone():
                detail = json.dumps({'message': 'Создан пустой постоянный граф', 'legacyBackup': backup}, ensure_ascii=False)
                db.execute('INSERT INTO permanent_revisions VALUES (0,?,?,?,?)', (now(), 'init', detail, encode(empty_graph())))
        validate_graph(self.read()['state'])

    def read(self):
        with self.connect() as db:
            row = db.execute('SELECT * FROM permanent_revisions ORDER BY id DESC LIMIT 1').fetchone()
            return {'revision': row['id'], 'state': decode(row['state'])}

    def history(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,time,action,detail FROM permanent_revisions ORDER BY id DESC')]

    def iter_snapshots(self):
        with self.lock, self.connect() as db:
            for raw in db.execute('SELECT * FROM permanent_revisions ORDER BY id'):
                row = dict(raw)
                row['state'] = decode(row['state'])
                yield row

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

    def diagnostics(self):
        with self.connect() as db:
            init = json.loads(db.execute('SELECT detail FROM permanent_revisions WHERE id=0').fetchone()[0])
            legacy_rows = db.execute('SELECT count(*) FROM revisions').fetchone()[0] if db.execute("SELECT 1 FROM sqlite_master WHERE name='revisions'").fetchone() else 0
            imports = db.execute('SELECT count(*) FROM permanent_imports').fetchone()[0]
        return {'mode': 'permanent', 'database': str(self.path), 'legacyRowsProtected': legacy_rows, 'legacyBackup': init.get('legacyBackup'), 'importedHistoryArchives': imports}

    def import_preview(self, document):
        incoming = parse_document(document)
        existing = self.read()['state']
        if incoming == existing:
            return {'duplicates': True, 'counts': {k: len(incoming[k]) for k in COLLECTIONS}}
        merged = self.merge_import(existing, incoming)
        return {'duplicates': False, 'additions': {k: len(merged[k]) - len(existing[k]) for k in COLLECTIONS},
                'definitions': len(merged['definitionDrafts']) - len(existing['definitionDrafts'])}

    @staticmethod
    def merge_import(existing, incoming):
        result = copy.deepcopy(existing)
        # Import adds exact IDs; conflicts never silently replace existing operators' work.
        for key in (*COLLECTIONS, 'definitionDrafts'):
            indexed = {v['id']: v for v in result[key]}
            for item in incoming[key]:
                if item['id'] in indexed:
                    if indexed[item['id']] != item:
                        raise Invalid(f'Импорт конфликтует с существующим ID {item["id"]}; автоматической замены нет.')
                else:
                    result[key].append(copy.deepcopy(item))
        for did, value in incoming['definitionPublications'].items():
            if did in result['definitionPublications'] and result['definitionPublications'][did] != value:
                raise Invalid('Конфликт подтверждённого определения при импорте.')
            result['definitionPublications'][did] = copy.deepcopy(value)
        validate_graph(result)
        return result

    def mutate(self, action, data, revision):
        from app.builder import operate
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM permanent_revisions ORDER BY id DESC LIMIT 1').fetchone()
            if revision != row['id']:
                raise Conflict('Граф изменился в другой вкладке. Обновите страницу и повторите действие.')
            state = decode(row['state'])
            result, detail = {}, action
            if action in ('definition_save', 'definition_publish'):
                result, detail = operate(state, action, data)
            elif action == 'position':
                node = lookup(state['nodes'], data.get('nodeId'), 'концепт')
                node.update(x=data.get('x'), y=data.get('y'))
                detail = 'Изменена позиция концепта'
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
