import copy
import tempfile
import unittest
from pathlib import Path
from app.permanent import PermanentStore, parse_document, validate_graph
from app.scenes import signature
from app.thoughts import missing, continuations, geometry
from app.store import Invalid, Conflict


class ThoughtsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'workspace.sqlite3'
        self.store = PermanentStore(self.path)
        self.call('definition_save', draft={'id': 'origin', 'title': 'Ручной разбор', 'definition': '',
                  'nodes': [], 'edges': [], 'contextEdges': [], 'routes': []})
        ops = []
        for i in ('object', 'process', 'xxx', 'screw', 'fall', 'floor', 'human', 'strike'):
            ops.append({'op': 'put', 'collection': 'nodes', 'value': {'id': i, 'label': '', 'designationOnly': True,
                        'structure': 'concept', 'kind': '', 'notes': '', 'x': 0, 'y': 0}})
        for i, a, b in [('os', 'object', 'screw'), ('op', 'object', 'process'), ('pf', 'process', 'fall'),
                        ('px', 'process', 'xxx'), ('xf', 'xxx', 'floor'), ('hh', 'human', 'human')]:
            ops.append({'op': 'put', 'collection': 'edges', 'value': {'id': i, 'from': a, 'to': b, 'role': 'relation', 'type': '', 'notes': ''}})
        ops.append({'op': 'put', 'collection': 'contextEdges', 'value': {'id': 'permission', 'from': 'os', 'to': 'pf'}})
        self.call('graph_apply', operations=ops, definitionId='origin', confirmed=True, previewRevision=self.store.read()['revision'])
        self.call('thought_alias', nodeId='object', alias='Объект')
        self.call('thought_alias', nodeId='process', alias='Процесс')
        self.new()

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])['result']

    def state(self):
        return self.store.read()['state']

    def complete(self):
        # Technical fixtures explicitly associate the whole literal input and
        # confirm it; these values do not claim linguistic correctness.
        d = self.draft()
        n = next(n for n in d['config']['nodes'] if n['included'])
        self.call('thought_save', draftId=d['id'], anchors=[{'id': n['id'], 'start': 0, 'end': len(d['text'])}])
        self.call('thought_confirm', draftId=d['id'], confirmed=True)
        return self.call('thought_complete', draftId=d['id'])

    def draft(self, ident=None):
        lab = self.state()['thoughtLab']
        return copy.deepcopy(next(d for d in lab['drafts'] if d['id'] == (ident or lab['currentDraftId'])))

    def new(self, text='Винт упал на пол', template=None):
        return self.call('thought_new', text=text, templateId=template)['draftId']

    def config(self):
        nodes = [{'id': 'local-' + i, 'conceptId': i, 'value': v, 'required': i in ('object', 'process'), 'included': True}
                 for i, v in [('object', 'Винт'), ('process', 'упал'), ('screw', 'Винт'), ('fall', 'упал'), ('xxx', 'на пол'), ('floor', 'пол')]]
        edges = [{**e, 'id': 'local-' + e['id'], 'edgeId': e['id'], 'template': signature(e),
                  'from': 'local-' + e['from'], 'to': 'local-' + e['to'], 'required': e['id'] == 'op', 'included': True, 'activation': 'direct'}
                 for e in self.state()['edges'] if e['id'] != 'hh']
        return {'nodes': nodes, 'edges': edges, 'contexts': [{'id': 'local-permission', 'contextId': 'permission',
                'template': {'id': 'permission', 'from': 'os', 'to': 'pf'}, 'from': 'local-os', 'to': 'local-pf', 'required': False, 'included': True}]}

    def save(self, config=None, **data):
        d = self.draft()
        return self.call('thought_save', draftId=d['id'], config=config or d['config'], **data)

    def template(self):
        self.save(self.config(), selection=[0, 4], anchors=[{'start': 0, 'end': 4, 'id': 'local-object'}])
        return self.call('thought_template', draftId=self.draft()['id'], label='Ручная конструкция')['templateId']

    def fill_core(self):
        c = self.draft()['config']
        for n in c['nodes']:
            if n['required']:
                n['value'] = 'Винт' if n['conceptId'] == 'object' else 'упал'
        self.save(c)

    def test_persistence_alias_anonymous_spans_no_alpha_and_direct_activity(self):
        self.template()
        before = self.state()
        self.assertEqual(before['designations'], [])
        self.assertTrue(all(n['structure'] == 'concept' for n in before['nodes']))
        self.assertEqual(next(n for n in before['nodes'] if n['id'] == 'object')['operatorAlias'], 'Объект')
        self.assertEqual(self.draft()['anchors'][0]['id'], 'local-object')
        result = self.complete()
        entry = self.state()['sceneLab']['scenes'][0]['entries'][0]
        self.assertEqual(entry['id'], result['entryId'])
        self.assertTrue(all(f['activation'] == 'direct' for f in entry['assertions']))
        self.assertEqual(PermanentStore(self.path).read(), self.store.read())

    def test_optional_xxx_omitted_short_thought_is_complete(self):
        t = self.template()
        self.new('Винт упал', t)
        self.fill_core()
        self.assertEqual(missing(self.draft()), [])
        self.complete()
        scene = self.state()['sceneLab']['scenes'][0]
        self.assertEqual({o['conceptId'] for o in scene['objects']}, {'object', 'process'})
        self.assertEqual([f['edgeId'] for f in scene['entries'][0]['assertions']], ['op'])

    def test_incomplete_keeps_draft_and_selected_contract_no_automatic_fallback(self):
        t = self.template()
        ident = self.new('Человек ударил', t)
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.call('thought_complete', draftId=ident)
        self.assertEqual(self.store.read(), before)
        c = self.draft()['config']
        c['nodes'][0]['required'] = False
        with self.assertRaises(Invalid):
            self.save(c)
        self.assertEqual(self.draft()['templateRef']['id'], t)

    def test_same_node_set_different_relation_structure_distinguished(self):
        self.template()
        a = self.state()['thoughtLab']['templates'][0]['config']
        self.call('thought_detach', draftId=self.draft()['id'])
        c = self.draft()['config']
        c['edges'] = [e for e in c['edges'] if e['edgeId'] != 'op']
        self.save(c)
        self.call('thought_template', draftId=self.draft()['id'], label='Другая структура')
        b = self.state()['thoughtLab']['templates'][1]['config']
        self.assertEqual(a['nodes'], b['nodes'])
        self.assertNotEqual(geometry(a), geometry(b))

    def test_template_refinement_is_explicit_and_old_application_is_pinned(self):
        t = self.template()
        old = self.draft()['id']
        self.new('Новое применение', t)
        self.call('thought_detach', draftId=self.draft()['id'])
        c = self.draft()['config']
        c['nodes'][0]['required'] = False
        self.save(c)
        self.call('thought_template', draftId=self.draft()['id'], templateId=t, label='Уточнение')
        self.assertEqual(self.draft(old)['templateRef']['version'], 1)
        self.assertEqual(self.draft()['templateRef']['version'], 2)
        self.assertTrue(self.draft(old)['contract']['nodes'][0]['required'])

    def test_continuation_is_not_fact_and_two_applications_are_independent(self):
        self.template()
        first = self.draft()['id']
        c = self.draft()['config']
        next(e for e in c['edges'] if e['edgeId'] == 'pf')['included'] = False
        self.save(c)
        rows = continuations(self.draft())
        self.assertEqual(len(rows), 1)
        # M021 opens an empty dynamic session at phrase input, without facts.
        self.assertTrue(all(not s['entries'] and s['kind'] == 'dialogue' for s in self.state()['sceneLab']['scenes']))
        self.call('thought_step', draftId=first, targetId=rows[0]['to'], contextId=rows[0]['contextId'])
        self.assertEqual(continuations(self.draft()), [])
        self.assertEqual(next(e for e in self.draft()['config']['edges'] if e['edgeId'] == 'pf')['activation'], 'context')
        t = self.draft()['templateRef']['id']
        second = self.new('Гайка упала на землю', t)
        self.assertNotEqual(first, second)
        self.assertFalse(next(e for e in self.draft()['config']['edges'] if e['edgeId'] == 'pf')['included'])
        self.assertTrue(next(e for e in self.draft(first)['config']['edges'] if e['edgeId'] == 'pf')['included'])

    def test_no_step_between_two_local_uses_of_shared_concept(self):
        c = self.config()
        duplicate = {**c['nodes'][0], 'id': 'other-object', 'value': 'Винт №2'}
        c['nodes'].append(duplicate)
        # Shared object concept binds different local objects: permission op -> os.
        self.call('graph_apply', definitionId='origin', operations=[{'op': 'put', 'collection': 'contextEdges',
                  'value': {'id': 'p2', 'from': 'op', 'to': 'os'}}], confirmed=True, previewRevision=self.store.read()['revision'])
        target = next(e for e in c['edges'] if e['edgeId'] == 'os')
        target.update(included=False, **{'from': 'other-object'})
        c['contexts'] = [{'id': 'local-p2', 'contextId': 'p2', 'from': 'local-op', 'to': 'local-os',
                         'template': {'id': 'p2', 'from': 'op', 'to': 'os'}, 'required': False, 'included': True}]
        self.save(c)
        self.assertEqual(continuations(self.draft()), [])
        with self.assertRaises(Invalid):
            self.call('thought_step', draftId=self.draft()['id'], targetId='local-os', contextId='local-p2')

    def test_repeated_human_concept_has_independent_instances(self):
        c = {'nodes': [{'id': i, 'conceptId': 'human', 'value': v, 'required': True, 'included': True}
                       for i, v in [('person-a', 'Человек №1'), ('person-b', 'Человек №2')]],
             'edges': [{'id': 'participation', 'edgeId': 'hh', 'from': 'person-a', 'to': 'person-b',
                        'template': signature(next(e for e in self.state()['edges'] if e['id'] == 'hh')),
                        'included': True, 'required': True, 'activation': 'direct'}], 'contexts': []}
        self.save(c)
        self.complete()
        objects = self.state()['sceneLab']['scenes'][0]['objects']
        self.assertEqual(objects[0]['conceptId'], objects[1]['conceptId'])
        self.assertNotEqual(objects[0]['id'], objects[1]['id'])
        self.assertNotEqual(objects[0]['label'], objects[1]['label'])

    def test_three_required_elements_reject_short_input_with_no_fallback(self):
        c = self.config()
        c['nodes'][4]['required'] = True
        self.save(c)
        t = self.call('thought_template', draftId=self.draft()['id'], label='Три обязательных')['templateId']
        self.new('Человек ударил', t)
        c = self.draft()['config']
        for n in c['nodes'][:2]:
            n['value'] = 'Заполнено'
        self.save(c)
        self.assertEqual(missing(self.draft()), ['local-xxx'])
        with self.assertRaises(Invalid):
            self.call('thought_complete', draftId=self.draft()['id'])

    def test_candidates_do_not_create_confirmed_knowledge(self):
        before = copy.deepcopy(self.state()['contextEdges'])
        self.call('thought_candidate', **{'from': 'op', 'to': 'xf', 'reason': 'Ручная гипотеза, семантика не проверена'})
        candidate = self.state()['thoughtLab']['candidates'][0]['id']
        self.assertEqual(self.state()['contextEdges'], before)
        with self.assertRaises(Invalid):
            self.call('thought_decide', candidateId=candidate, status='accepted', decision='Ещё нет разрешения')
        self.call('thought_decide', candidateId=candidate, status='rejected', decision='Недостаточно оснований')
        self.assertEqual(self.state()['contextEdges'], before)

    def test_accept_candidate_requires_separate_graph_edit_and_reason(self):
        self.call('thought_candidate', **{'from': 'op', 'to': 'xf', 'reason': 'Операторский кандидат'})
        candidate = self.state()['thoughtLab']['candidates'][0]['id']
        self.call('graph_apply', definitionId='origin', operations=[{'op': 'put', 'collection': 'contextEdges',
                  'value': {'id': 'explicit-permission', 'from': 'op', 'to': 'xf'}}], confirmed=True,
                  previewRevision=self.store.read()['revision'])
        before = copy.deepcopy(self.state()['contextEdges'])
        self.call('thought_decide', candidateId=candidate, status='accepted', decision='Оператор явно создал разрешение')
        self.assertEqual(self.state()['contextEdges'], before)
        self.assertEqual(self.state()['thoughtLab']['candidates'][0]['status'], 'accepted')

    def test_empty_completion_and_context_activation_cannot_be_forged(self):
        c = self.config()
        c['edges'][0]['activation'] = 'context'
        with self.assertRaises(Invalid):
            self.save(c)
        c = self.config()
        for key in c:
            for item in c[key]:
                item.update(required=False, included=False)
        self.save(c)
        with self.assertRaises(Invalid):
            self.call('thought_complete', draftId=self.draft()['id'])

    def test_completed_scene_mapping_cannot_change_values_between_instances(self):
        self.save(self.config())
        self.complete()
        state = self.state()
        objects = state['sceneLab']['scenes'][0]['objects']
        objects[0]['label'], objects[1]['label'] = 'Чужое значение', 'Другое чужое значение'
        with self.assertRaises(Invalid):
            validate_graph(state)

    def test_revision_export_import_restore_and_conflicts(self):
        t = self.template()
        before = self.store.read()
        self.complete()
        self.new('Незавершённый ввод', t)
        with self.assertRaises(Conflict):
            self.store.mutate('thought_alias', {'nodeId': 'xxx', 'alias': 'устарело'}, before['revision'])
        doc = self.store.export()
        self.assertEqual(doc['version'], 5)
        self.assertEqual(parse_document(doc), self.state())
        target = PermanentStore(Path(self.tmp.name) / 'import.sqlite3')
        target.mutate('import', {'document': doc, 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], self.state())
        target.mutate('import', {'document': doc, 'confirmed': True}, target.read()['revision'])
        self.assertEqual(target.read()['state'], self.state())
        changed = copy.deepcopy(doc)
        changed.pop('history')
        changed.pop('historyEncoding')
        changed['state']['thoughtLab']['drafts'][0]['text'] = 'Конфликт ID'
        with self.assertRaises(Invalid):
            target.import_preview(changed)
        self.call('restore', targetRevision=before['revision'], confirmed=True)
        self.assertEqual(self.state(), before['state'])
        self.assertEqual(self.store.export()['version'], 5)

    def test_graph_references_protected_and_corrupt_anchors_rejected(self):
        self.template()
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.call('graph_apply', operations=[{'op': 'delete', 'collection': 'edges', 'id': 'op'}],
                      confirmed=True, previewRevision=before['revision'])
        self.assertEqual(self.store.read(), before)
        with self.assertRaises(Invalid):
            self.save(anchors=[{'id': 'local-object', 'start': 0, 'end': 10000}])
        state = self.state()
        state['thoughtLab']['drafts'][0]['config']['edges'][0]['from'] = 'local-floor'
        with self.assertRaises(Invalid):
            validate_graph(state)


if __name__ == '__main__':
    unittest.main()
