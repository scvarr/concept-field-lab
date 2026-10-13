from contextlib import closing
import copy
import hashlib
import json
import sqlite3
import shutil
import tempfile
import unittest
import threading
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch
from app.store import Store, uid, Invalid, Conflict
from app.permanent import PermanentStore, empty_graph, parse_document, logical_digest
from app.definitions import Definitions, SensesParser


class PermanentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'workspace.sqlite3'
        self.store = PermanentStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])

    def draft(self):
        nodes = [{'id': uid(), 'designation': s, 'existing': False} for s in ('гайка', 'деталь', 'резьба', 'внутренний')]
        edges = [{'id': uid(), 'from': nodes[a]['id'], 'to': nodes[b]['id'], 'existing': False} for a,b in ((0,1),(1,2),(1,3))]
        return {'id': uid(), 'title': 'Техническая проба', 'definition': 'Ручное определение', 'nodes': nodes,
            'edges': edges, 'contextEdges': [{'id': uid(), 'from': edges[0]['id'], 'to': edges[1]['id']}],
            'routes': [{'id': uid(), 'edgeIds': [e['id'] for e in edges[:2]]}]}

    def publish(self, draft):
        self.call('definition_save', draft=draft)
        return self.call('definition_publish', draftId=draft['id'], confirmed=True)

    def test_empty_graph_and_legacy_operations_rejected(self):
        self.assertEqual(self.store.read(), {'revision': 0, 'state': empty_graph()})
        for action in ('create_study','create_accumulation','merge','match','accumulation_add_source'):
            with self.assertRaises(Invalid):
                self.call(action)
        self.assertEqual(self.store.read()['revision'], 0)

    def test_http_default_interface_cache_and_legacy_routes_absent(self):
        from app.server import make_server
        response={'parse':{'title':'гайка','revid':123,'text':'<h1>Русский</h1><h4>Значение</h4><ol><li>Тестовое определение</li></ol>'}}
        server=make_server(self.path,0,definition_fetcher=lambda _:response)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            self.assertIn('permanent-panel',urlopen(url).read().decode('utf-8'))
            initial=json.load(urlopen(url+'/api/state'))
            self.assertEqual(initial['state'],empty_graph())
            for route in ('/api/proposals','/api/accumulation-index','/api/graph-export'):
                with self.assertRaises(HTTPError) as caught:urlopen(url+route)
                self.assertEqual(caught.exception.code,404)
            first=json.load(urlopen(url+'/api/definitions?lemma=%D0%B3%D0%B0%D0%B9%D0%BA%D0%B0'))
            second=json.load(urlopen(url+'/api/definitions?lemma=%D0%B3%D0%B0%D0%B9%D0%BA%D0%B0'))
            self.assertEqual(first['status'],'online');self.assertEqual(second['status'],'cache')
            payload=json.dumps({'action':'definition_save','revision':0,'data':{'draft':self.draft()}}).encode()
            request=Request(url+'/api/action',data=payload,headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as caught:urlopen(request)
            self.assertEqual(caught.exception.code,403)
            request.add_header('X-Workspace-Token',initial['token'])
            self.assertEqual(json.load(urlopen(request))['revision'],1)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_import_conflict_and_corrupt_context_atomic(self):
        self.publish(self.draft());document=self.store.export();before=self.store.read()
        bad=copy.deepcopy(document);bad.pop('history');bad.pop('historyEncoding');bad['state']['contextEdges'][0]['to']=uid()
        with self.assertRaises(Invalid):self.call('import',document=bad,confirmed=True)
        self.assertEqual(self.store.read(),before)
        conflict=copy.deepcopy(document);conflict.pop('history');conflict.pop('historyEncoding');conflict['state']['designations'][0]['text']='Другой текст того же ID'
        with self.assertRaises(Invalid):self.call('import',document=conflict,confirmed=True)
        self.assertEqual(self.store.read(),before)

    def test_same_designation_does_not_identify_concepts(self):
        from app.dictionary import search
        draft=self.draft();draft['nodes'][2]['designation']='гайка'
        state=self.publish(draft)['state']
        results=search(state,'гайка')
        ids={c['nodeId'] for c in results['concepts']}
        self.assertEqual(ids,{draft['nodes'][0]['id'],draft['nodes'][2]['id']})
        self.assertTrue(results['multipleConcepts'])
        self.assertTrue(all(c['location']=='permanent' and c['selectable'] for c in results['concepts']))

    def test_direct_ids_reuse_context_edit_export_import_restart(self):
        d = self.draft()
        first = self.publish(d)['state']
        self.assertEqual({n['id'] for n in first['nodes']}, {n['id'] for n in d['nodes']})
        self.assertEqual({e['id'] for e in first['edges']}, {e['id'] for e in d['edges']})
        self.assertNotIn('studies', first)
        self.assertNotIn('accumulation', first)
        self.publish(d)
        self.assertEqual(self.store.read()['state'], first)
        second = {'id': uid(), 'title': 'Повтор', 'definition': 'Второй ввод', 'nodes': [], 'edges': [], 'contextEdges': [], 'routes': []}
        for n in first['nodes'][:2]:
            second['nodes'].append({'id': n['id'], 'designation': '', 'existing': True, 'base': n})
        second['edges'] = [{**d['edges'][0], 'existing': True}]
        result = self.publish(second)['state']
        self.assertEqual(result['nodes'], first['nodes'])
        self.assertEqual(result['edges'], first['edges'])
        self.assertEqual(len(result['definitionPublications']), 2)
        self.assertEqual(PermanentStore(self.path).read()['state'], result)
        document = self.store.export()
        restored = PermanentStore(Path(self.temp.name)/'restored.sqlite3')
        self.assertFalse(restored.import_preview(document)['duplicates'])
        restored.mutate('import', {'document': document, 'confirmed': True}, 0)
        self.assertEqual(restored.read()['state'], result)
        self.assertEqual(restored.export()['importedHistory'][0], document)
        parse_document(restored.export())
        self.assertTrue(restored.import_preview(document)['duplicates'])
        rev = restored.read()['revision']
        restored.mutate('import', {'document': document, 'confirmed': True}, rev)
        self.assertEqual(restored.read()['revision'], rev)
        self.assertEqual(restored.diagnostics()['importedHistoryArchives'],1)
        with self.assertRaises(Invalid):
            restored.import_preview(json.loads(Path('data/experiments/accumulation/k001-k002-workspace.json').read_text(encoding='utf-8')))

    def test_backup_legacy_wal_and_untouched_history(self):
        path = Path(self.temp.name)/'legacy.sqlite3'
        legacy = Store(path)
        legacy.mutate('create_study', {'title':'Старая запись'}, 0)
        before = legacy.read()
        # Keep a live WAL writer connected: file-copy backup would be insufficient.
        with closing(sqlite3.connect(path)) as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE proof (id TEXT)')
            writer.execute("INSERT INTO proof VALUES ('WAL entry')")
            writer.commit()
            new = PermanentStore(path)
            info = new.diagnostics()['legacyBackup']
            self.assertEqual(new.read()['state'], empty_graph())
            self.assertEqual(Store(path).read(), before)
            backup = Path(info['backupPath'])
            self.assertEqual(hashlib.sha256(backup.read_bytes()).hexdigest(), info['sha256'])
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('SELECT * FROM proof').fetchone()[0], 'WAL entry')
                self.assertEqual(logical_digest(db), info['logicalSha256'])
            recovery=Path(self.temp.name)/'recovery.sqlite3'
            shutil.copyfile(backup,recovery)
            self.assertEqual(Store(recovery).read(), before)
            self.assertEqual(hashlib.sha256(backup.read_bytes()).hexdigest(), info['sha256'])
            self.assertEqual(PermanentStore(path).diagnostics()['legacyBackup'], info)

    def test_backup_failure_prevents_new_table_and_unknown_sqlite_refused(self):
        path = Path(self.temp.name)/'protected.sqlite3'
        legacy = Store(path)
        before = legacy.read()
        with patch('app.permanent.verified_backup', side_effect=OSError('no backup space')):
            with self.assertRaises(OSError):
                PermanentStore(path)
        self.assertEqual(Store(path).read(), before)
        with closing(sqlite3.connect(path)) as db:
            self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='permanent_revisions'").fetchone())
        path2 = Path(self.temp.name)/'other.sqlite3'
        with closing(sqlite3.connect(path2)) as db:
            db.execute('CREATE TABLE unrelated (id INTEGER)')
        raw = path2.read_bytes()
        with self.assertRaises(Invalid):
            PermanentStore(path2)
        self.assertEqual(path2.read_bytes(), raw)

    def test_context_integrity_shared_object_protection_stale_and_restore(self):
        d = self.draft()
        first = self.publish(d)['state']
        second = {'id': uid(), 'title':'Reuse', 'definition':'Другой ввод', 'nodes':[], 'edges':[{**d['edges'][0],'existing':True}], 'contextEdges':[], 'routes':[]}
        second['nodes']=[{'id':n['id'],'existing':True,'designation':'','base':n} for n in first['nodes'][:2]]
        self.publish(second)
        d['edges']=d['edges'][1:];d['contextEdges']=[];d['routes']=[]
        self.call('definition_save', draft=d)
        before=self.store.read()
        with self.assertRaises(Invalid):
            self.call('definition_publish',draftId=d['id'],confirmed=True)
        self.assertEqual(self.store.read(),before)
        with self.assertRaises(Conflict):
            self.store.mutate('restore',{'targetRevision':0,'confirmed':True},0)
        self.call('restore',targetRevision=0,confirmed=True)
        self.assertEqual(self.store.read()['state'],empty_graph())
        self.assertGreater(len(self.store.history()),len(before['state']['definitionDrafts']))


class DefinitionsTest(unittest.TestCase):
    def test_multiple_russian_senses_excludes_other_languages_and_examples(self):
        parser=SensesParser()
        parser.feed('<h1>Русский</h1><h2>слово I</h2><h4>Значение</h4><ol><li>первое ◆ пример</li><li>второе</li></ol><h4>Синонимы</h4><ol><li>не значение</li></ol><h1>Белорусский</h1><h4>Значение</h4><ol><li>другой язык</li></ol>')
        self.assertEqual([s['text'] for s in parser.senses],['первое','второе'])
    def test_cache_offline_missing_network_and_no_graph_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            fetch=lambda _: {'parse':{'title':'гайка','revid':123,'text':'<h2>Русский</h2><h3>гайка I</h3><h4>Значение</h4><ol><li>тестовое толкование</li></ol>'}}
            service=Definitions(temp,fetch)
            result=service.get('гайка')
            self.assertEqual(result['status'],'online')
            self.assertEqual(result['senses'][0]['source']['revision'],123)
            self.assertEqual(result['senses'][0]['source']['license'],'CC BY-SA 4.0')
            offline=Definitions(temp,lambda _: (_ for _ in ()).throw(OSError('offline')))
            self.assertEqual(offline.get('гайка')['status'],'cache')
            self.assertEqual(offline.get('гайка',True)['status'],'offline-cache')
            self.assertEqual(offline.get('несуществующий',True)['status'],'unavailable')
            missing=Definitions(temp,lambda _: {'error':{'code':'missingtitle'}})
            self.assertEqual(missing.get('нет статьи')['status'],'missing')
