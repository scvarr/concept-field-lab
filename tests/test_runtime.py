"""Current HTTP surface, graph invariants and the supported exchange boundary."""
from contextlib import closing
import copy
import hashlib
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.permanent import PermanentStore, VERSION, parse_document
from app.server import make_server
from app.store import Invalid, Conflict


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'workspace.sqlite3'
        self.store = PermanentStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, operations):
        return self.store.mutate('graph_apply', {'operations': operations, 'confirmed': True,
                                 'previewRevision': self.store.read()['revision']}, self.store.read()['revision'])

    def nodes(self):
        return [{'op': 'put', 'collection': 'nodes', 'value': {
            'id': i, 'structure': 'concept', 'label': '', 'designationOnly': True,
            'kind': '', 'notes': '', 'x': 0, 'y': 0}} for i in ['a', 'b', 'c']]

    def test_smoke_http_empty_database_and_static_dependency_closure(self):
        server = make_server(self.path, 0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            page = urlopen(base).read().decode()
            snapshot = json.load(urlopen(base + '/api/state'))
            self.assertEqual(snapshot['state']['nodes'], [])
            self.assertNotIn('definitionDrafts', snapshot['state'])
            self.assertNotIn('/builder.js', page)
            for route in ['/api/history', '/api/export', '/api/manage-index', '/style.css',
                          '/layout-worker.js', '/layout-engine.js', '/vendor/d3-7.9.0.min.js',
                          '/vendor/dagre-1.1.5.min.js', *re.findall(r'<script src="([^"]+)"', page)]:
                self.assertEqual(urlopen(base + route).status, 200, route)
            for route in ['/api/dictionary', '/api/definitions', '/api/legacy-backup',
                          '/api/graph-export', '/app.js', '/builder.js', '/legacy.html', '/../../AGENTS.md']:
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + route)
                self.assertEqual(error.exception.code, 404, route)
            payload = json.dumps({'action': 'position', 'revision': 0, 'data': {}}).encode()
            for headers in [{}, {'X-Workspace-Token': snapshot['token'], 'Origin': 'https://other.invalid'}]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + '/api/action', data=payload, headers=headers))
                self.assertEqual(error.exception.code, 403)
            headers = {'X-Workspace-Token': snapshot['token'], 'Content-Type': 'application/json'}
            document = json.load(urlopen(base + '/api/export'))
            preview = json.load(urlopen(Request(base + '/api/import-preview',
                                    data=json.dumps({'document': document}).encode(), headers=headers)))
            self.assertTrue(preview['duplicates'])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_context_integrity_alpha_and_atomic_revision_guard(self):
        self.apply(self.nodes() + [{'op': 'put', 'collection': 'edges', 'value': {
            'id': i, 'from': a, 'to': b, 'role': 'relation', 'type': ''}}
            for i, a, b in [('ab', 'a', 'b'), ('bc', 'b', 'c')]])
        self.apply([{'op': 'put', 'collection': 'contextEdges', 'value': {
            'id': 'permission', 'from': 'ab', 'to': 'bc'}}])
        before = self.store.read()
        for operation in [
            {'op': 'delete', 'collection': 'nodes', 'id': 'a'},
            {'op': 'delete', 'collection': 'edges', 'id': 'ab'},
            {'op': 'put', 'collection': 'contextEdges', 'value': {'id': 'x', 'from': 'ab', 'to': 'ab'}},
            {'op': 'put', 'collection': 'contextEdges', 'value': {'id': 'x', 'from': 'ab', 'to': 'bc'}},
            {'op': 'put', 'collection': 'nodes', 'value': {'id': 'a', 'structure': 'alpha'}},
        ]:
            with self.assertRaises(Invalid):
                self.apply([operation])
            self.assertEqual(self.store.read(), before)
        with self.assertRaises(Conflict):
            self.store.mutate('position', {'nodeId': 'a', 'x': 2, 'y': 3}, before['revision'] - 1)
        self.apply([{'op': 'put', 'collection': 'contextEdges', 'value': {
            'id': 'reverse', 'from': 'bc', 'to': 'ab'}}])
        self.assertEqual(len(self.store.read()['state']['contextEdges']), 2)

    def test_v7_roundtrip_history_restore_and_old_formats_rejected(self):
        self.apply(self.nodes())
        before = self.store.read()
        self.store.mutate('position', {'nodeId': 'a', 'x': 30, 'y': 60}, before['revision'])
        document = self.store.export()
        self.assertEqual(document['version'], VERSION)
        self.assertEqual(parse_document(document), self.store.read()['state'])
        target = PermanentStore(Path(self.temp.name) / 'import.sqlite3')
        target.mutate('import', {'document': document, 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], self.store.read()['state'])
        self.assertEqual(parse_document(target.export()), target.read()['state'])
        self.store.mutate('restore', {'targetRevision': before['revision'], 'confirmed': True},
                          self.store.read()['revision'])
        self.assertEqual(self.store.read()['state'], before['state'])
        self.assertGreater(len(self.store.history()), 2)
        for version in range(1, VERSION):
            old = {**document, 'version': version}
            with self.assertRaises(Invalid):
                parse_document(old)
        corrupt = copy.deepcopy(document)
        corrupt['state']['nodes'][0]['x'] = -99
        with self.assertRaises(Invalid):
            parse_document(corrupt)

    def test_historical_sqlite_rejected_without_modification(self):
        path = Path(self.temp.name) / 'old.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE revisions (state TEXT)')
            db.execute("INSERT INTO revisions VALUES ('historical data')")
            db.commit()
        digest = hashlib.sha256(path.read_bytes()).digest()
        with self.assertRaises(Invalid):
            PermanentStore(path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)
