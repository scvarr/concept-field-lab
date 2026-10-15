import copy
import tempfile
import unittest
from pathlib import Path
from app.graph_editor import prepare, usages
from app.permanent import PermanentStore, parse_document
from app.store import Invalid, Conflict
from scripts.unified_editor_fixture import populate


class GraphEditorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'graph.sqlite3'
        self.store = PermanentStore(self.path)
        populate(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])

    def apply(self, operations, **data):
        return self.call('graph_apply', operations=operations, confirmed=True,
                         previewRevision=self.store.read()['revision'], **data)

    def state(self):
        return self.store.read()['state']

    def redirect(self, delete=True):
        uses = usages(self.state(), 'detail')
        return {'op': 'redirect', 'source': 'detail', 'target': 'part',
                'uses': [{'id': e['id'], 'end': end} for e in uses['edges'] for end in ('from', 'to') if e[end] == 'detail'],
                'designationIds': [d['id'] for d in uses['designations']],
                'definitionIds': list(uses['definitions']), 'deleteSource': delete}

    def region(self, ids):
        did = self.call('graph_checkout', nodeIds=ids)['result']['draftId']
        return copy.deepcopy(next(d for d in self.state()['definitionDrafts'] if d['id'] == did))

    def test_full_redirect_stable_ids_components_context_designation_and_history(self):
        before = self.store.read()
        op = self.redirect()
        preview_state, preview = prepare(before['state'], {'operations': [op]})
        self.assertEqual(self.store.read(), before)
        self.assertEqual(len(preview['affectedContexts']), 2)
        self.assertEqual(set(preview['affectedDefinitions']), {'definition-detail', 'definition-screw', 'definition-nut'})
        result = self.apply([op])
        self.assertEqual(result['state'], preview_state)
        state = result['state']
        self.assertNotIn('detail', [n['id'] for n in state['nodes']])
        self.assertEqual({e['id'] for e in state['edges']}, {e['id'] for e in before['state']['edges']})
        self.assertEqual(state['contextEdges'], before['state']['contextEdges'])
        self.assertEqual(next(d for d in state['designations'] if d['id'] == 'word-detail')['target'], 'part')
        self.assertTrue(all('detail' not in p['nodeIds'] for p in state['definitionPublications'].values()))
        self.assertEqual({e['id']: e['role'] for e in state['edges']}, {e['id']: e['role'] for e in before['state']['edges']})
        self.assertEqual(PermanentStore(self.path).read(), self.store.read())
        document = self.store.export()
        self.assertEqual(parse_document(document), state)
        target = PermanentStore(Path(self.temp.name) / 'import.sqlite3')
        target.mutate('import', {'document': document, 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], state)
        self.assertEqual(target.export()['importedHistory'][0]['history'], document['history'])
        self.call('restore', targetRevision=before['revision'], confirmed=True)
        self.assertEqual(self.state(), before['state'])

    def test_selected_uses_only(self):
        before = self.state()
        self.apply([{'op': 'redirect', 'source': 'detail', 'target': 'part',
                     'uses': [{'id': 'screw-detail', 'end': 'to'}]}])
        changed = [e['id'] for e in self.state()['edges'] if e != next(v for v in before['edges'] if v['id'] == e['id'])]
        self.assertEqual(changed, ['screw-detail'])
        self.assertEqual(self.state()['designations'], before['designations'])
        self.assertEqual(self.state()['contextEdges'], before['contextEdges'])

    def test_remaining_dependencies_block_delete_atomically(self):
        before = self.store.read()
        op = self.redirect()
        op['uses'].pop()
        with self.assertRaises(Invalid):
            self.apply([op])
        self.assertEqual(self.store.read(), before)
        op = self.redirect(); op['definitionIds'] = []
        with self.assertRaises(Invalid):
            self.apply([op])
        self.assertEqual(self.store.read(), before)

    def test_dangling_context_role_change_and_empty_alpha_refused(self):
        before = self.store.read()
        for ops in ([{'op': 'delete', 'collection': 'edges', 'id': 'screw-detail'}],
                    [{'op': 'put', 'collection': 'edges', 'value': {'id': 'screw-detail', 'role': 'component'}}],
                    [{'op': 'delete', 'collection': 'edges', 'id': 'nut-detail-component'}],
                    [{'op': 'delete', 'collection': 'nodes', 'id': 'detail'}]):
            with self.assertRaises(Invalid):
                self.apply(ops)
            self.assertEqual(self.store.read(), before)

    def test_cycle_and_duplicate_component_no_implicit_merge(self):
        before = self.store.read()
        op = self.redirect(False); op['target'] = 'screw'
        with self.assertRaises(Invalid):
            self.apply([op])
        self.assertEqual(self.store.read(), before)
        with self.assertRaises(Invalid):
            self.apply([{'op': 'put', 'collection': 'edges', 'value': {'id': 'duplicate', 'from': 'screw', 'to': 'detail', 'role': 'component'}}], definitionId='definition-screw')
        self.assertEqual(self.store.read(), before)

    def test_region_edits_shared_object_and_external_graph_updates_clean_region(self):
        draft = self.region(['detail', 'metal'])
        draft['nodes'][0]['notes'] = 'Из миниграфа'
        self.call('definition_save', draft=draft)
        self.call('definition_publish', draftId=draft['id'], confirmed=True)
        self.assertEqual(next(n for n in self.state()['nodes'] if n['id'] == 'detail')['notes'], 'Из миниграфа')
        self.apply([{'op': 'put', 'collection': 'nodes', 'value': {'id': 'detail', 'notes': 'Из общего графа'}}])
        fresh = next(d for d in self.state()['definitionDrafts'] if d['id'] == draft['id'])
        self.assertEqual(fresh['nodes'][0]['notes'], 'Из общего графа')
        self.assertNotIn('graphStale', fresh)

    def test_dirty_and_legacy_drafts_preserved_and_cannot_overwrite(self):
        draft = self.region(['detail', 'metal'])
        draft['nodes'][0]['notes'] = 'Незавершённая правка'
        self.call('definition_save', draft=draft)
        self.apply([{'op': 'put', 'collection': 'nodes', 'value': {'id': 'detail', 'notes': 'Новая правка'}}])
        saved = next(d for d in self.state()['definitionDrafts'] if d['id'] == draft['id'])
        self.assertEqual(saved['nodes'][0]['notes'], 'Незавершённая правка')
        self.assertIn('graphStale', saved)
        # A browser holding an older copy must not erase the persisted conflict marker.
        self.call('definition_save', draft=draft)
        for did in (draft['id'], 'definition-detail', 'definition-screw', 'definition-nut'):
            before = self.store.read()
            with self.assertRaises(Invalid):
                self.call('definition_publish', draftId=did, confirmed=True)
            self.assertEqual(self.store.read(), before)

    def test_region_create_and_delete_relations_and_context_atomic(self):
        draft = self.region(['detail', 'screw', 'nut', 'metal'])
        draft['contextEdges'] = [c for c in draft['contextEdges'] if c['id'] != 'context-cross']
        draft['edges'] = [e for e in draft['edges'] if e['id'] != 'screw-detail']
        draft['edges'].append({'id': 'new-relation', 'from': 'screw', 'to': 'metal', 'existing': False})
        self.call('definition_save', draft=draft)
        self.call('definition_publish', draftId=draft['id'], confirmed=True)
        self.assertNotIn('screw-detail', [e['id'] for e in self.state()['edges']])
        self.assertNotIn('context-cross', [c['id'] for c in self.state()['contextEdges']])
        self.assertIn('new-relation', [e['id'] for e in self.state()['edges']])
        parse_document(self.store.export())

    def test_preview_revision_and_http_conflict_guards(self):
        before = self.store.read()
        op = {'op': 'put', 'collection': 'nodes', 'value': {'id': 'detail', 'notes': 'Новое'}}
        self.call('definition_save', draft=self.state()['definitionDrafts'][0])
        self.apply([op])
        after = self.store.read()
        with self.assertRaises(Invalid):
            self.call('graph_apply', operations=[op], confirmed=True, previewRevision=before['revision'])
        with self.assertRaises(Conflict):
            self.store.mutate('graph_apply', {'operations': [op], 'confirmed': True, 'previewRevision': after['revision']}, before['revision'])
        self.assertEqual(self.store.read(), after)

    def test_direct_create_edit_delete_node_alpha_edge_context(self):
        self.apply([{'op': 'put', 'collection': 'nodes', 'value': {'id': 'temporary', 'structure': 'concept', 'label': '', 'designationOnly': True, 'kind': '', 'notes': '', 'x': 0, 'y': 0}}], definitionId='definition-part')
        self.apply([{'op': 'put', 'collection': 'nodes', 'value': {'id': 'temporary', 'structure': 'alpha'}},
                    {'op': 'put', 'collection': 'edges', 'value': {'id': 'temporary-component', 'from': 'temporary', 'to': 'part', 'role': 'component'}}], definitionId='definition-part')
        self.apply([{'op': 'delete', 'collection': 'edges', 'id': 'temporary-component'},
                    {'op': 'delete', 'collection': 'nodes', 'id': 'temporary'}])
        self.assertNotIn('temporary', [n['id'] for n in self.state()['nodes']])

    def test_old_browser_cannot_promote_pending_values_to_auto_refreshed_base(self):
        draft = self.region(['detail', 'metal'])
        self.apply([{'op': 'put', 'collection': 'nodes', 'value': {'id': 'detail', 'notes': 'Свежие данные'}}])
        draft['definition'] = 'Несохранённый текст старой вкладки'
        self.call('definition_save', draft=draft)
        saved = next(d for d in self.state()['definitionDrafts'] if d['id'] == draft['id'])
        self.assertEqual(saved['definition'], draft['definition'])
        self.assertEqual(saved['graphBase'], draft['graphBase'])
        self.assertIn('graphStale', saved)
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.call('definition_publish', draftId=draft['id'], confirmed=True)
        self.assertEqual(self.store.read(), before)

    def test_clean_region_reopens_without_extra_drafts_but_dirty_is_kept(self):
        first = self.region(['detail', 'metal'])
        second = self.region(['metal', 'detail'])
        self.assertEqual(first['id'], second['id'])
        second['nodes'][0]['notes'] = 'Незавершённое'
        self.call('definition_save', draft=second)
        third = self.region(['detail', 'metal'])
        self.assertNotEqual(first['id'], third['id'])
        saved = next(d for d in self.state()['definitionDrafts'] if d['id'] == first['id'])
        self.assertEqual(saved['nodes'][0]['notes'], 'Незавершённое')

    def test_parallel_relations_require_explicit_reason(self):
        op = {'op': 'put', 'collection': 'edges', 'value': {'id': 'parallel', 'from': 'screw', 'to': 'detail', 'role': 'relation'}}
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.apply([op], definitionId='definition-screw')
        self.assertEqual(self.store.read(), before)
        op['value']['parallelReason'] = 'Явное операторское различие'
        self.apply([op], definitionId='definition-screw')
        self.assertIn('parallel', [e['id'] for e in self.state()['edges']])

    def test_nested_alpha_definitions_and_external_context_appear_in_preview(self):
        s = self.state()
        draft = {'id': 'definition-parent', 'title': 'Родительская α', 'definition': 'Вложенное повторное использование.',
                 'nodes': [{'id': 'parent', 'structure': 'alpha', 'existing': False, 'designations': []},
                           *[{'id': i, 'existing': True, 'base': next(n for n in s['nodes'] if n['id'] == i)} for i in ('screw', 'detail', 'metal')]],
                 'edges': [{'id': 'parent-component', 'from': 'parent', 'to': 'screw', 'role': 'component', 'existing': False},
                           {'id': 'parent-metal', 'from': 'parent', 'to': 'metal', 'existing': False},
                           {'id': 'screw-detail', 'from': 'screw', 'to': 'detail', 'existing': True}],
                 'contextEdges': [{'id': 'parent-context', 'from': 'parent-metal', 'to': 'screw-detail'}], 'routes': []}
        self.call('definition_save', draft=draft)
        self.call('definition_publish', draftId=draft['id'], confirmed=True)
        uses = usages(self.state(), 'detail')
        self.assertIn('parent', uses['ancestorIds'])
        self.assertIn('definition-parent', uses['definitions'])
        self.assertIn('parent-metal', [e['id'] for e in uses['indirectEdges']])
        _, preview = prepare(self.state(), {'operations': [{'op': 'redirect', 'source': 'detail', 'target': 'part',
                                                'uses': [{'id': 'screw-detail-component', 'end': 'to'}]}]})
        self.assertIn('definition-parent', preview['affectedDefinitions'])
        self.assertIn('parent-context', [c['id'] for c in preview['affectedContexts']])
