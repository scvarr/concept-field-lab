import copy
import tempfile
import unittest
from pathlib import Path
from app.permanent import PermanentStore, parse_document, validate_graph
from app.scenes import projection, continuations, observe
from app.store import Invalid, Conflict
from scripts.scenes_fixture import populate, call


class ScenesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'lab.sqlite3'
        self.store = PermanentStore(self.path)
        self.ids = populate(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, **data):
        return call(self.store, action, **data)

    def state(self):
        return self.store.read()['state']

    def scene(self, ident):
        return next(s for s in self.state()['sceneLab']['scenes'] if s['id'] == self.ids.get(ident, ident))

    def workspace(self):
        return self.state()['sceneLab']['workspaces'][0]

    def rejected(self, action, **data):
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.call(action, **data)
        self.assertEqual(self.store.read(), before)

    def test_A_B_facts_only_in_scenes_exact_context_no_automatic_loading(self):
        state = self.state()
        self.assertEqual(len(state['nodes']), 3)
        self.assertEqual(len(state['edges']), 3)
        self.assertNotIn('Гайка', str(state['nodes']))
        self.assertEqual(len(projection(self.scene('knowledge'))), 1)
        self.assertEqual(self.scene('physics')['links'], [self.ids['knowledge']])
        before = copy.deepcopy(state)
        self.call('scene_context', sceneId=self.ids['dialogue'], text='Физика')
        self.assertEqual(self.state()['nodes'], before['nodes'])
        self.assertEqual(self.state()['sceneLab']['workspaces'], before['sceneLab']['workspaces'])
        self.rejected('scene_context', sceneId=self.ids['dialogue'], text='Неизвестная наука')
        self.call('scene_create', label='Физика', kind='knowledge')
        self.rejected('scene_context', sceneId=self.ids['dialogue'], text='Физика')

    def test_C_identity_history_and_no_physical_inference(self):
        scene = self.scene('dialogue')
        entries = scene['entries']
        self.assertEqual(len(entries), 4)  # context + three manually structured messages
        self.assertEqual({f['from'] for e in entries for f in e['assertions']}, {self.ids['screw']})
        self.assertEqual(projection(scene, 2)[0]['to'], self.ids['table'])
        self.assertEqual(projection(scene, 3), [])  # fall does not infer final resting place
        self.assertEqual(projection(scene)[0]['to'], self.ids['floor'])
        self.assertEqual(entries[2]['kind'], 'event')
        self.assertEqual(entries[1]['assertions'][0]['to'], self.ids['table'])
        # Another event, without an explicit retraction, cannot silently alter location.
        self.call('scene_input', sceneId=scene['id'], text='Ещё событие', kind='event', assertions=[{
            'edgeId': 'fall', 'from': self.ids['screw'], 'to': self.ids['table']}])
        self.assertEqual(projection(self.scene('dialogue'))[0]['to'], self.ids['floor'])

    def test_explicit_slot_replaces_only_this_object_and_keeps_history(self):
        screw2 = self.call('scene_object', sceneId=self.ids['dialogue'], label='Винт №2', conceptId='item')['objectId']
        def write(obj, place):
            return self.call('scene_input', sceneId=self.ids['dialogue'], kind='state', text='Ручное положение',
                             assertions=[{'edgeId': 'location', 'from': obj, 'to': place, 'slot': 'положение'}])
        write(screw2, self.ids['table'])
        write(self.ids['screw'], self.ids['table'])
        write(self.ids['screw'], self.ids['floor'])
        active = projection(self.scene('dialogue'))
        self.assertEqual({f['from']: f['to'] for f in active}, {self.ids['screw']: self.ids['floor'], screw2: self.ids['table']})
        self.assertEqual(len(self.scene('dialogue')['entries']), 7)

    def test_D_independent_copies_provenance_restart_export_import_restore(self):
        workspace = self.workspace()
        a, b = workspace['bundles']
        self.assertEqual(a['assertions'][0]['activation'], 'seed')
        self.assertEqual(b['assertions'][0]['activation'], 'inactive')
        self.assertNotEqual(a['objects'][0]['id'], b['objects'][0]['id'])
        self.assertNotEqual(a['objects'][0]['structure']['rootId'], b['objects'][0]['structure']['rootId'])
        self.assertEqual(a['assertions'][0]['origin']['assertionId'], self.ids['nutFact'])
        self.assertEqual(PermanentStore(self.path).read(), self.store.read())
        document = self.store.export()
        self.assertEqual(document['version'], 3)
        self.assertEqual(parse_document(document), self.state())
        target = PermanentStore(Path(self.temp.name) / 'import.sqlite3')
        self.assertEqual(target.import_preview(document)['sceneAdditions'], {'scenes': 3, 'workspaces': 1})
        target.mutate('import', {'document': document, 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], self.state())
        target.mutate('import', {'document': document, 'confirmed': True}, target.read()['revision'])
        self.assertEqual(target.read()['state'], self.state())
        before = self.store.read()
        self.call('scene_reset', workspaceId=workspace['id'])
        self.call('restore', targetRevision=before['revision'], confirmed=True)
        self.assertEqual(self.state(), before['state'])
        altered = copy.deepcopy(document)
        altered['version'] = 2
        with self.assertRaises(Invalid):
            parse_document(altered)
        # A restore before scenes existed must not downgrade their later history.
        self.call('restore', targetRevision=0, confirmed=True)
        restored = self.store.export()
        self.assertNotIn('sceneLab', restored['state'])
        self.assertEqual(restored['version'], 3)
        self.assertEqual(parse_document(restored), self.state())

    def test_local_step_requires_direction_loaded_pair_and_same_extraction(self):
        dialogue = self.ids['dialogue']
        detail = self.call('scene_object', sceneId=dialogue, label='Деталь', conceptId='category')['objectId']
        classification = self.call('scene_input', sceneId=dialogue, text='Винт — деталь', kind='state', assertions=[{
            'edgeId': 'classification', 'from': self.ids['screw'], 'to': detail}])['assertionIds'][0]
        location = projection(self.scene('dialogue'))[0]['id']
        extracted = self.call('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=dialogue,
                              assertionIds=[classification, location])
        seed, dest = extracted['assertionIds']
        self.rejected('scene_step', workspaceId=self.ids['workspace'], assertionId=dest, fromId=seed, contextId='classification-location')
        self.call('scene_seed', workspaceId=self.ids['workspace'], assertionId=seed)
        candidates = continuations(self.workspace())
        self.assertEqual(candidates, [{'from': seed, 'to': dest, 'contextId': 'classification-location'}])
        self.call('scene_step', workspaceId=self.ids['workspace'], assertionId=dest, fromId=seed, contextId='classification-location')
        self.assertEqual(self.workspace()['bundles'][-1]['assertions'][1]['activation'], 'context')
        # No global traversal and no cross-bundle borrowing, even for same template.
        extra = self.call('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=dialogue, assertionIds=[location])
        self.assertEqual(continuations(self.workspace()), [])
        self.rejected('scene_step', workspaceId=self.ids['workspace'], assertionId=extra['assertionIds'][0], fromId=seed, contextId='classification-location')
        self.call('scene_reset', workspaceId=self.ids['workspace'])
        self.assertTrue(all(f['activation'] == 'inactive' for b in self.workspace()['bundles'] for f in b['assertions']))

    def test_bad_bindings_stale_tabs_graph_dependencies_and_import_conflicts_atomic(self):
        self.rejected('scene_input', sceneId=self.ids['dialogue'], text='Неверные концы', kind='state', assertions=[{
            'edgeId': 'classification', 'from': self.ids['screw'], 'to': self.ids['floor']}])
        self.rejected('scene_input', sceneId=self.ids['dialogue'], text='Неверное снятие', kind='event', retracts=[self.ids['nutFact']])
        edge = next(e for e in self.state()['edges'] if e['id'] == 'location')
        self.rejected('graph_apply', operations=[{'op': 'put', 'collection': 'edges', 'value': {**edge, 'type': 'новое значение'}}],
                      confirmed=True, previewRevision=self.store.read()['revision'])
        self.rejected('graph_apply', operations=[{'op': 'delete', 'collection': 'nodes', 'id': 'place'}],
                      confirmed=True, previewRevision=self.store.read()['revision'])
        self.rejected('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=self.ids['knowledge'], assertionIds=['unknown'])
        before = self.store.read()
        with self.assertRaises(Conflict):
            self.store.mutate('scene_create', {'label': 'Устаревшая запись', 'kind': 'knowledge'}, before['revision'] - 1)
        self.assertEqual(self.store.read(), before)
        document = self.store.export()
        self.call('scene_object', sceneId=self.ids['knowledge'], label='Другой объект', conceptId='item')
        self.rejected('import', document=document, confirmed=True)

    def test_bounded_extraction_and_missing_context_no_unrelated_scene_loading(self):
        unrelated = self.call('scene_create', label='Другая область', kind='knowledge')['sceneId']
        self.rejected('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=unrelated, assertionIds=[self.ids['nutFact']])
        self.rejected('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=self.ids['knowledge'], assertionIds=[])
        # The 201st selected fact is rejected before any instance is committed.
        scene = self.scene('knowledge')
        original = scene['entries'][0]['assertions'][0]
        for count in (199, 2):
            self.call('scene_input', sceneId=scene['id'], text='Синтетический предел', kind='state', assertions=[{
                'edgeId': original['edgeId'], 'from': original['from'], 'to': original['to']} for _ in range(count)])
        ids = [f['id'] for f in projection(self.scene('knowledge'))]
        self.rejected('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=scene['id'], assertionIds=ids)

    def test_shared_template_does_not_activate_another_objects_state(self):
        dialogue = self.ids['dialogue']
        other = self.call('scene_object', sceneId=dialogue, label='Другой винт', conceptId='item')['objectId']
        category = self.call('scene_object', sceneId=dialogue, label='Деталь', conceptId='category')['objectId']
        classification = self.call('scene_input', sceneId=dialogue, text='Другой винт — деталь', kind='state', assertions=[{
            'edgeId': 'classification', 'from': other, 'to': category}])['assertionIds'][0]
        location = projection(self.scene('dialogue'))[0]['id']
        copied = self.call('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=dialogue,
                           assertionIds=[classification, location])['assertionIds']
        self.call('scene_seed', workspaceId=self.ids['workspace'], assertionId=copied[0])
        self.assertEqual(continuations(self.workspace()), [])
        self.rejected('scene_step', workspaceId=self.ids['workspace'], assertionId=copied[1], fromId=copied[0], contextId='classification-location')

    def test_nested_alpha_is_copied_per_object_and_source_changes_do_not_rewrite_copies(self):
        # A purely structural probe, not a proposed meaning of a nut/screw.
        draft = {'id': 'alpha-probe', 'title': 'Состав для технической пробы', 'definition': 'Вложенные α без смыслового утверждения.',
                 'nodes': [{'id': i, 'designation': i, 'existing': False, 'structure': 'alpha' if i in ('outer', 'inner') else 'concept'}
                           for i in ('outer', 'inner', 'leaf')],
                 'edges': [{'id': i, 'from': a, 'to': b, 'existing': False, 'role': role}
                           for i, a, b, role in [('outer-inner', 'outer', 'inner', 'component'),
                                                 ('inner-leaf', 'inner', 'leaf', 'component'), ('outer-link', 'outer', 'leaf', 'relation')]],
                 'contextEdges': [], 'routes': []}
        self.call('definition_save', draft=draft)
        self.call('definition_publish', draftId=draft['id'], confirmed=True)
        sid = self.call('scene_create', label='Проба α', kind='knowledge')['sceneId']
        a = self.call('scene_object', sceneId=sid, label='Первое использование α', conceptId='outer')['objectId']
        b = self.call('scene_object', sceneId=sid, label='Второе использование α', conceptId='outer')['objectId']
        leaf = self.call('scene_object', sceneId=sid, label='Объект листа', conceptId='leaf')['objectId']
        assertions = self.call('scene_input', sceneId=sid, text='Два явных заполнения', kind='state', assertions=[
            {'edgeId': 'outer-link', 'from': obj, 'to': leaf} for obj in (a, b)])['assertionIds']
        self.call('scene_link', sceneId=self.ids['dialogue'], targetId=sid)
        self.call('scene_extract', workspaceId=self.ids['workspace'], sourceSceneId=sid, assertionIds=assertions)
        copies = self.workspace()['bundles'][-1]['objects']
        roots = [o['structure'] for o in copies if o['conceptId'] == 'outer']
        self.assertEqual([len(r['nodes']) for r in roots], [3, 3])
        self.assertTrue(set(n['id'] for n in roots[0]['nodes']).isdisjoint(n['id'] for n in roots[1]['nodes']))
        before = copy.deepcopy(self.workspace())
        node = next(n for n in self.state()['nodes'] if n['id'] == 'leaf')
        self.call('graph_apply', operations=[{'op': 'put', 'collection': 'nodes', 'value': {**node, 'notes': 'Новое описание'}}],
                  confirmed=True, previewRevision=self.store.read()['revision'])
        self.assertEqual(self.workspace(), before)
        validate_graph(self.state())

    def test_scene_reference_cycles_do_not_recurse_or_load_data(self):
        self.call('scene_link', sceneId=self.ids['knowledge'], targetId=self.ids['physics'])
        computed = observe(self.state())
        self.assertEqual(set(computed['reachable'][self.ids['dialogue']]), {self.ids['knowledge'], self.ids['physics']})
        self.assertEqual(len(self.workspace()['bundles']), 2)


if __name__ == '__main__':
    unittest.main()
