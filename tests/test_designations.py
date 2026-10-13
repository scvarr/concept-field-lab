import copy
import tempfile
import unittest
from pathlib import Path
from app.permanent import PermanentStore, parse_document
from app.store import uid, Invalid, Conflict
from app.dictionary import search


class DesignationsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'aliases.sqlite3'
        self.store = PermanentStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])

    def draft(self):
        nodes = [{'id': uid(), 'existing': False, 'designation': word,
                  'designations': [{'id': uid(), 'text': word}]} for word in ('деталь', 'птица', 'внутренний', 'резьба')]
        edges = [{'id': uid(), 'existing': False, 'from': nodes[a]['id'], 'to': nodes[b]['id']}
                 for a,b in ((0,2), (2,3), (1,2))]
        return {'id': uid(), 'title': 'Техническая проверка входов', 'definition': 'Выбор оператора в тесте',
                'nodes': nodes, 'edges': edges, 'routes': [{'id': uid(), 'edgeIds': [e['id'] for e in edges[:2]]}],
                'contextEdges': [{'id': uid(), 'from': edges[0]['id'], 'to': edges[1]['id']}]}

    def publish(self, draft):
        self.call('definition_save', draft=draft)
        return self.call('definition_publish', draftId=draft['id'], confirmed=True)['state']

    def test_many_to_many_draft_source_edit_restart_import(self):
        draft = self.draft()
        source = {'name': 'Русский Викисловарь', 'entry': 'гайка I', 'senseId': '1', 'revision': 14297625,
                  'revisionUrl': 'https://ru.wiktionary.org/w/index.php?oldid=14297625', 'lemma': 'гайка'}
        for index, sense in ((0,'1'), (1,'5')):
            draft['nodes'][index]['designations'].append({'id': uid(), 'text': 'гайка', 'lexicalSource': {**source, 'senseId': sense}})
        initial = self.publish(draft)
        results = search(initial, 'гайка')
        self.assertEqual({c['nodeId'] for c in results['concepts']}, {n['id'] for n in draft['nodes'][:2]})
        self.assertTrue(results['multipleConcepts'])
        self.assertTrue(all(c['edges'] and c['designations'] and c['origins'] for c in results['concepts']))
        node_id = draft['nodes'][0]['id']
        alias = next(d for d in initial['designations'] if d['target'] == node_id and d['text'] == 'гайка')
        self.call('designation_save', nodeId=node_id, designationId=alias['id'], text='гайка крепёжная', lexicalSource=source)
        edited = self.store.read()['state']
        for key in ('nodes', 'edges', 'contextEdges', 'definitionPublications', 'definitionDrafts'):
            self.assertEqual(initial[key], edited[key])
        self.assertEqual(len(edited['designations']), 6)
        self.assertEqual(len(search(edited, 'гайка')['concepts']), 2)
        # An old caption and stale initial designation rows cannot overwrite the edit.
        again = self.publish(draft)
        self.assertEqual(again['designations'], edited['designations'])
        self.call('designation_remove', designationId=alias['id'])
        self.publish(draft)
        state = self.store.read()['state']
        self.assertEqual(len(search(state, 'гайка')['concepts']), 1)
        self.assertEqual(state['edges'], initial['edges'])
        self.assertEqual(state['contextEdges'], initial['contextEdges'])
        self.assertEqual(PermanentStore(self.path).read()['state'], state)
        document = self.store.export()
        self.assertEqual(parse_document(document), state)
        second = PermanentStore(Path(self.temp.name) / 'import.sqlite3')
        self.assertEqual(second.mutate('import', {'document': document, 'confirmed': True}, 0)['state'], state)
        self.assertEqual(parse_document(second.export()), state)

    def test_last_designation_removal_and_new_alias_keep_structure(self):
        draft = self.draft()
        state = self.publish(draft)
        ident = state['designations'][0]['id'];node_id = state['designations'][0]['target']
        self.call('designation_remove', designationId=ident)
        removed = self.publish(draft)
        self.assertFalse(any(d['target'] == node_id for d in removed['designations']))
        self.assertEqual(search(removed,node_id)['concepts'][0]['labels'], [])
        result = self.call('designation_save', nodeId=node_id, text='точка входа')['result']
        self.assertNotEqual(result['designationId'], ident)
        self.assertEqual(self.publish(draft)['edges'], state['edges'])
        self.assertEqual(self.store.read()['state']['contextEdges'], state['contextEdges'])

    def test_reuse_shared_id_keeps_all_aliases_across_both_definitions(self):
        first = self.draft();state = self.publish(first)
        node = state['nodes'][0]
        self.call('designation_save', nodeId=node['id'], text='гайка')
        second = {'id': uid(), 'title': 'Повторное использование', 'definition': 'Вторая проба',
                  'nodes': [{'id': n['id'], 'existing': True, 'base': copy.deepcopy(n)} for n in state['nodes'][:3]],
                  'edges': [{**first['edges'][0], 'existing': True}], 'routes': [], 'contextEdges': []}
        shared = self.publish(second)
        self.assertEqual(len(shared['nodes']), 4)
        self.assertEqual(len(shared['edges']), 3)
        self.assertEqual(len(shared['designations']), 5)
        self.assertEqual(self.publish(first)['designations'], shared['designations'])

    def test_invalid_edits_stale_revision_and_import_are_atomic(self):
        state = self.publish(self.draft());before = self.store.read();alias=state['designations'][0]
        for data in ({'text':''}, {'text':'x','lexicalSource':{'name':''}}, {'text':'x','lexicalSource':{'name':'test','revision':[]}},
                     {'text':'x','nodeId':state['nodes'][1]['id']}):
            with self.assertRaises(Invalid):
                self.call('designation_save', **{'nodeId':alias['target'], 'designationId':alias['id'], **data})
        with self.assertRaises(Conflict):
            self.store.mutate('designation_remove', {'designationId':alias['id']}, 0)
        self.assertEqual(self.store.read(), before)
        draft = self.draft();draft['nodes'][0]['designations'][0]['id']=draft['edges'][0]['id']
        with self.assertRaises(Invalid):self.call('definition_save', draft=draft)
        self.assertEqual(self.store.read(), before)

    def test_pending_aliases_not_graph_until_confirmation(self):
        draft=self.draft();draft['nodes'][0]['designations']=[]
        self.call('definition_save',draft=draft)
        self.assertFalse(self.store.read()['state']['nodes'])
        state=self.publish(draft)
        self.assertEqual(len(state['nodes']),4)
        self.assertEqual(len(state['designations']),3)


if __name__ == '__main__':
    unittest.main()
