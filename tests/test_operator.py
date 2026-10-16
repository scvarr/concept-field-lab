import copy
import tempfile
import unittest
from pathlib import Path
from app.permanent import PermanentStore, parse_document
from app.lifecycle import prepare, catalog
from app.scenes import signature
from app.thoughts import missing, content_gaps, uncovered
from app.store import Invalid, Conflict


class OperatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'own.sqlite3'
        self.store = PermanentStore(self.path)
        ops = []
        for ident in ('object', 'process', 'screw', 'fall', 'roll', 'xxx'):
            ops.append({'op': 'put', 'collection': 'nodes', 'value': {'id': ident, 'label': '', 'designationOnly': True,
                        'structure': 'concept', 'kind': '', 'notes': '', 'x': 0, 'y': 0}})
        for ident, a, b in [('os', 'object', 'screw'), ('op', 'object', 'process'), ('pf', 'process', 'fall'), ('pr', 'process', 'roll')]:
            ops.append({'op': 'put', 'collection': 'edges', 'value': {'id': ident, 'from': a, 'to': b, 'role': 'relation', 'type': ''}})
        self.graph(ops)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])['result']

    def state(self):
        return self.store.read()['state']

    def graph(self, operations, **data):
        return self.call('graph_apply', operations=operations, confirmed=True,
                         previewRevision=self.store.read()['revision'], **data)

    def new(self, text='Винт упал', template=None):
        return self.call('thought_new', text=text, templateId=template)['draftId']

    def draft(self, ident):
        return copy.deepcopy(next(d for d in self.state()['thoughtLab']['drafts'] if d['id'] == ident))

    def config(self, event='fall'):
        nodes = [{'id': 'local-' + ident, 'conceptId': ident, 'value': value, 'required': ident in ('object', 'process'), 'included': True}
                 for ident, value in [('object', 'винт №1'), ('process', event), ('screw', 'винт'), (event, event)]]
        nodes[0].update(bindingRequired=True, contentEdges=['local-os'])
        es = [e for e in self.state()['edges'] if e['id'] in ('os', 'op', 'pf' if event == 'fall' else 'pr')]
        return {'nodes': nodes, 'edges': [{'id': 'local-' + e['id'], 'edgeId': e['id'], 'from': 'local-' + e['from'],
                'to': 'local-' + e['to'], 'template': signature(e), 'included': True, 'required': e['id'] != 'os', 'activation': 'direct'} for e in es], 'contexts': []}

    def save(self, ident, config=None):
        d = self.draft(ident)
        return self.call('thought_save', draftId=ident, config=config or d['config'],
                         anchors=[{'id': 'local-object', 'start': 0, 'end': len(d['text'])}])

    def complete(self, ident):
        self.call('thought_confirm', draftId=ident, confirmed=True)
        return self.call('thought_complete', draftId=ident)

    def plan(self, keys, mode='delete'):
        return prepare(self.state(), {'selection': keys, 'mode': mode}, self.store.read()['revision'])[1]

    def delete(self, keys, dependents=False, mode='delete'):
        preview = self.plan(keys, mode)
        if dependents:
            keys += [v['key'] for v in preview['blocked']]
            preview = self.plan(keys, mode)
        return self.call('manage_apply', selection=keys, mode=mode, confirmed=True,
                         previewRevision=preview['revision'], previewHash=preview['hash'])

    def test_new_graph_objects_need_no_definition_or_blank_draft(self):
        state = self.state()
        self.assertTrue(all('definitionId' not in v and v['origins'] for k in ('nodes', 'edges') for v in state[k]))
        n = copy.deepcopy(state['nodes'][0]); n['notes'] = 'Правка общего ID'
        self.graph([{'op': 'put', 'collection': 'nodes', 'value': n}])

    def test_template_fullness_does_not_establish_content_fullness(self):
        ident = self.new()
        self.save(ident, self.config())
        self.call('thought_template', draftId=ident, label='Тестовая структура')
        template = self.draft(ident)['templateRef']['id']
        second = self.new(template=template)
        c = self.draft(second)['config']
        for n in c['nodes']:
            if n['included']:
                n['value'] = n['conceptId']
        self.save(second, c)
        self.assertEqual(missing(self.draft(second)), [])
        self.assertEqual(content_gaps(self.draft(second)), ['local-object'])
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.complete(second)
        self.assertEqual(self.store.read(), before)
        for n in c['nodes']:
            n.update(included=True, value=n['conceptId'])
        for e in c['edges']:
            e['included'] = True
        self.save(second, c)
        self.complete(second)
        entry = self.state()['sceneLab']['scenes'][0]['entries'][0]
        self.assertIn('os', [f['edgeId'] for f in entry['assertions']])
        self.assertNotIn('xxx', [o['conceptId'] for o in self.state()['sceneLab']['scenes'][0]['objects']])

    def test_unmapped_text_and_changed_bindings_invalidate_confirmation(self):
        ident = self.new('Винт упал')
        self.call('thought_save', draftId=ident, config=self.config())
        self.assertTrue(uncovered(self.draft(ident)))
        with self.assertRaises(Invalid):
            self.call('thought_confirm', draftId=ident, confirmed=True)
        self.save(ident)
        self.call('thought_confirm', draftId=ident, confirmed=True)
        c = self.draft(ident)['config']; c['nodes'][0]['value'] = 'другой'
        self.save(ident, c)
        self.assertFalse(self.draft(ident)['representation']['confirmed'])
        with self.assertRaises(Invalid):
            self.call('thought_complete', draftId=ident)

    def test_same_scene_object_in_two_thoughts_independent_processes(self):
        first = self.new(); self.save(first, self.config()); self.complete(first)
        a = self.draft(first)
        obj = next(b['objectId'] for b in a['objectBindings'] if b['localId'] == 'local-object')
        second = self.new('Затем винт покатился')
        c = self.config('roll'); c['nodes'][0]['sceneObjectId'] = obj
        self.save(second, c); self.complete(second)
        b = self.draft(second)
        self.assertEqual(next(v['objectId'] for v in b['objectBindings'] if v['localId'] == 'local-object'), obj)
        self.assertNotEqual(next(v['objectId'] for v in a['objectBindings'] if v['localId'] == 'local-process'),
                            next(v['objectId'] for v in b['objectBindings'] if v['localId'] == 'local-process'))
        third = self.new(); self.save(third, self.config()); self.complete(third)
        self.assertNotEqual(next(v['objectId'] for v in self.draft(third)['objectBindings'] if v['localId'] == 'local-object'), obj)
        revised = self.call('thought_revise', draftId=first)['draftId']
        d = self.draft(revised)
        self.assertEqual(d['revisedFrom'], first)
        self.assertFalse(d['representation']['confirmed'])
        self.assertTrue(all(not n.get('sceneObjectId') for n in d['config']['nodes']))
        self.assertTrue(all(e['activation'] == 'direct' for e in d['config']['edges']))
        self.assertEqual(len(self.state()['sceneLab']['scenes'][0]['entries']), 3)

    def test_no_automatic_scene_identity_or_arbitrary_value_transfer(self):
        first = self.new(); self.save(first, self.config()); self.complete(first)
        obj = self.draft(first)['objectBindings'][0]['objectId']
        second = self.new(); c = self.config(); c['nodes'][0].update(sceneObjectId=obj, value='чужое значение')
        with self.assertRaises(Invalid):
            self.save(second, c)
        c['nodes'][0]['value'] = 'винт №1'; self.save(second, c)
        other_scene = self.call('scene_create', label='Другая сцена', kind='dialogue')['sceneId']
        with self.assertRaises(Invalid):
            self.call('thought_save', draftId=second, sceneId=other_scene)

    def test_delete_template_keeps_exact_contract_and_previous_applications(self):
        ident = self.new(); self.save(ident, self.config())
        tid = self.call('thought_template', draftId=ident, label='Прежняя конструкция')['templateId']
        self.complete(ident); contract = self.draft(ident)['contract']
        self.delete(['template:' + tid])
        d = self.draft(ident)
        self.assertEqual(d['contract'], contract)
        self.assertEqual(d['templateArchive']['id'], tid)
        self.assertEqual(self.state()['thoughtLab']['templates'], [])
        self.assertEqual(parse_document(self.store.export()), self.state())

    def test_delete_scene_and_graph_group_requires_explicit_dependency_selection(self):
        ident = self.new(); self.save(ident, self.config()); self.complete(ident)
        before = self.store.read()
        preview = self.plan(['node:object'])
        self.assertTrue(preview['blocked'])
        with self.assertRaises(Invalid):
            self.delete(['node:object'])
        self.assertEqual(self.store.read(), before)
        self.delete(['node:object'], dependents=True)
        self.assertNotIn('object', [n['id'] for n in self.state()['nodes']])
        parse_document(self.store.export())
        scene_id = self.state()['sceneLab']['scenes'][0]['id']
        self.delete(['scene:' + scene_id], dependents=True)
        self.assertEqual(self.state()['sceneLab']['scenes'], [])

    def test_delete_one_thought_keeps_shared_object_for_another(self):
        first = self.new(); self.save(first, self.config()); self.complete(first)
        obj = self.draft(first)['objectBindings'][0]['objectId']
        second = self.new(); c = self.config('roll'); c['nodes'][0]['sceneObjectId'] = obj
        self.save(second, c); self.complete(second)
        p = self.plan(['thought:' + first])
        self.assertNotIn('object:' + obj, [v['key'] for v in p['optional']])
        self.assertTrue(p['optional'])
        self.delete(['thought:' + first], dependents=True)
        self.assertEqual(len(self.state()['sceneLab']['scenes'][0]['entries']), 1)
        self.assertTrue(any(o['id'] == obj for o in self.state()['sceneLab']['scenes'][0]['objects']))
        parse_document(self.store.export())

    def test_last_alpha_component_and_accepted_candidate_are_visible_dependencies(self):
        self.graph([{'op': 'put', 'collection': 'nodes', 'value': {'id': 'alpha', 'label': '', 'designationOnly': True,
                    'structure': 'alpha', 'kind': '', 'notes': '', 'x': 0, 'y': 0}},
                    {'op': 'put', 'collection': 'edges', 'value': {'id': 'component', 'role': 'component', 'from': 'alpha', 'to': 'screw'}},
                    {'op': 'put', 'collection': 'contextEdges', 'value': {'id': 'permission', 'from': 'os', 'to': 'pf'}}])
        self.call('thought_candidate', **{'from': 'os', 'to': 'pf', 'reason': 'Ручной кандидат'})
        candidate = self.state()['thoughtLab']['candidates'][0]['id']
        self.call('thought_decide', candidateId=candidate, status='accepted', decision='Оператор создал разрешение')
        self.assertIn('node:alpha', [v['key'] for v in self.plan(['edge:component'])['blocked']])
        self.assertIn('candidate:' + candidate, [v['key'] for v in self.plan(['context:permission'])['blocked']])
        self.delete(['edge:component'], dependents=True)
        self.delete(['context:permission'], dependents=True)
        parse_document(self.store.export())

    def test_optional_orphan_cleanup_is_explicit_and_atomic(self):
        ident = self.new(); self.save(ident, self.config()); self.complete(ident)
        p = self.plan(['thought:' + ident])
        keys = [v['key'] for v in p['selected'] + p['blocked'] + p['optional']]
        self.assertTrue(p['optional'])
        self.delete(keys)
        scene = self.state()['sceneLab']['scenes'][0]
        self.assertEqual(scene['objects'], [])
        self.assertEqual(scene['entries'], [])

    def test_draft_delete_and_close_leave_no_automatic_old_canvas(self):
        first = self.new(); second = self.new('Другая')
        self.call('thought_close')
        self.assertIsNone(self.state()['thoughtLab']['currentDraftId'])
        self.call('thought_select', draftId=second)
        self.delete(['thought:' + second])
        self.assertIsNone(self.state()['thoughtLab']['currentDraftId'])
        self.assertEqual(self.state()['thoughtLab']['drafts'][0]['id'], first)

    def test_reset_is_atomic_revision_protected_restore_and_new_start_work(self):
        ident = self.new(); self.save(ident, self.config()); self.complete(ident)
        old = self.store.read(); preview = self.plan([], mode='reset')
        with self.assertRaises(Invalid):
            self.call('manage_apply', mode='reset', selection=[], confirmed=False,
                      previewRevision=preview['revision'], previewHash=preview['hash'])
        with self.assertRaises(Invalid):
            self.call('manage_apply', mode='reset', selection=[], confirmed=True,
                      previewRevision=preview['revision'], previewHash='changed')
        self.assertEqual(self.store.read(), old)
        self.delete([], mode='reset')
        self.assertEqual(self.state()['nodes'], [])
        self.assertNotIn('thoughtLab', self.state())
        self.new('После сброса')
        with self.assertRaises(Conflict):
            self.store.mutate('manage_apply', {'mode': 'reset'}, old['revision'])
        self.call('restore', targetRevision=old['revision'], confirmed=True)
        self.assertEqual(self.state(), old['state'])
        self.assertEqual(PermanentStore(self.path).read(), self.store.read())
        target = PermanentStore(Path(self.tmp.name) / 'import.sqlite3')
        target.mutate('import', {'document': self.store.export(), 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], self.state())

    def test_scene_links_retractions_and_workspaces_participate_in_dependencies(self):
        ident = self.new(); self.save(ident, self.config()); self.complete(ident)
        knowledge = self.call('thought_include', draftId=ident, label='Знание')['sceneId']
        source = next(v for v in self.state()['sceneLab']['scenes'] if v['id'] == knowledge)
        linked = self.call('scene_create', label='Связанное знание', kind='knowledge')['sceneId']
        self.call('scene_link', sceneId=linked, targetId=knowledge)
        dialogue = self.draft(ident)['sceneId']
        self.call('scene_link', sceneId=dialogue, targetId=knowledge)
        workspace = self.call('scene_workspace', sceneId=dialogue, label='Рабочая копия')['workspaceId']
        self.call('scene_extract', workspaceId=workspace, sourceSceneId=knowledge,
                  assertionIds=[v['id'] for v in source['entries'][0]['assertions']])
        state = self.state()
        rows = catalog(state)
        target = 'scene:' + knowledge
        _, preview = prepare(state, {'selection': [target]}, self.store.read()['revision'])
        kinds = {v['kind'] for v in preview['blocked']}
        self.assertTrue({'object', 'entry', 'link', 'workspace'} <= kinds)
        self.assertTrue(all(v['depends'] <= rows.keys() for v in rows.values()))

    def test_m021_include_two_statements_independent_and_idempotent(self):
        first = self.new('Винт — деталь'); self.save(first, self.config()); self.complete(first)
        original = self.draft(first)
        before = copy.deepcopy(self.state()['nodes']), copy.deepcopy(self.state()['edges'])
        source = next(s for s in self.state()['sceneLab']['scenes'] if s['id'] == original['sceneId'])
        self.assertEqual(source['entries'][0]['kind'], 'state')
        target = self.call('thought_include', draftId=first, label='Словарь')['sceneId']
        included = self.call('thought_include', draftId=first, sceneId=target)
        self.assertTrue(included['alreadyIncluded'])
        second = self.new('Головка — часть винта'); self.save(second, self.config()); self.complete(second)
        self.call('thought_include', draftId=second, sceneId=target)
        state = self.state()
        knowledge = next(s for s in state['sceneLab']['scenes'] if s['id'] == target)
        self.assertEqual(len(knowledge['entries']), 2)
        self.assertEqual([e['text'] for e in knowledge['entries']], ['Винт — деталь', 'Головка — часть винта'])
        self.assertTrue(all(e['kind'] == 'state' for e in knowledge['entries']))
        self.assertEqual(knowledge['entries'][0]['sourceEntryId'], original['entryId'])
        self.assertFalse({o['id'] for o in knowledge['objects']} & {o['id'] for o in source['objects']})
        self.assertEqual(before, (state['nodes'], state['edges']))
        self.assertEqual(state['sceneLab']['currentSceneId'], source['id'])
        self.assertEqual(state['sceneLab']['workspaces'], [])
        self.assertEqual(state['sceneLab']['scenes'][0]['links'], [])
        exported = self.store.export()
        self.assertEqual(parse_document(exported), state)
        restarted = PermanentStore(self.path)
        self.assertEqual(restarted.read()['state'], state)
        fresh = PermanentStore(Path(self.tmp.name) / 'import.sqlite3')
        fresh.mutate('import', {'document': exported, 'confirmed': True}, fresh.read()['revision'])
        self.assertEqual(fresh.read()['state'], state)
        fresh.mutate('import', {'document': exported, 'confirmed': True}, fresh.read()['revision'])
        self.assertEqual(fresh.read()['state'], state)
        rev = self.store.read()['revision']
        self.delete(['scene:' + target], dependents=True)
        self.assertNotIn(target, [s['id'] for s in self.state()['sceneLab']['scenes']])
        self.assertEqual(len(self.state()['thoughtLab']['drafts']), 2)
        self.call('restore', targetRevision=rev, confirmed=True)
        self.assertEqual(self.state(), state)

    def test_m021_invalid_inclusion_and_event_choice_are_atomic(self):
        ident = self.new(); self.save(ident, self.config())
        before = self.state()
        with self.assertRaises(Invalid):
            self.call('thought_include', draftId=ident, label='Нельзя черновик')
        self.assertEqual(self.state(), before)
        self.call('thought_confirm', draftId=ident, confirmed=True)
        with self.assertRaises(Invalid):
            self.call('thought_complete', draftId=ident, kind='inferred')
        self.call('thought_complete', draftId=ident, kind='event')
        self.assertEqual(self.state()['sceneLab']['scenes'][0]['entries'][0]['kind'], 'event')
        before = self.state()
        with self.assertRaises(Invalid):
            self.call('thought_include', draftId=ident, sceneId=before['sceneLab']['currentSceneId'])
        self.assertEqual(self.state(), before)
        self.call('scene_create', kind='knowledge', label='Тема')
        next_id = self.new('Новая фраза')
        scene = next(s for s in self.state()['sceneLab']['scenes'] if s['id'] == self.draft(next_id)['sceneId'])
        self.assertEqual(scene['kind'], 'dialogue')

    def test_m021_inclusion_provenance_is_validated(self):
        from app.permanent import validate_graph
        ident = self.new(); self.save(ident, self.config()); self.complete(ident)
        target = self.call('thought_include', draftId=ident, label='Словарь')['sceneId']
        for field, value in [('sourceSceneId', 'missing'), ('sourceEntryId', 'missing'), ('text', 'Чужой текст'), ('kind', 'event')]:
            altered = self.state()
            scene = next(s for s in altered['sceneLab']['scenes'] if s['id'] == target)
            scene['entries'][0][field] = value
            with self.assertRaises(Invalid):
                validate_graph(altered)
        altered = self.state()
        scene = next(s for s in altered['sceneLab']['scenes'] if s['id'] == target)
        scene['objects'][0]['sourceObjectId'] = 'missing'
        with self.assertRaises(Invalid):
            validate_graph(altered)
        altered = self.state()
        scene = next(s for s in altered['sceneLab']['scenes'] if s['id'] == target)
        scene['entries'][0]['assertions'][1]['localId'] = scene['entries'][0]['assertions'][0]['localId']
        with self.assertRaises(Invalid):
            validate_graph(altered)
