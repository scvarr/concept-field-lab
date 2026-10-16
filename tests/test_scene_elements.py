"""Explicit structural/content bindings: persistence, identity and edge permissions."""
import copy
import unittest
from pathlib import Path
import test_thoughts as fixtures
from app.permanent import PermanentStore, parse_document
from app.scenes import signature
from app.store import Invalid
from app.thoughts import continuations
from app.element_bindings import compact_config
from app.lifecycle import prepare


class SceneElementsTest(unittest.TestCase):
    setUp = fixtures.ThoughtsTest.setUp
    tearDown = fixtures.ThoughtsTest.tearDown
    call = fixtures.ThoughtsTest.call
    state = fixtures.ThoughtsTest.state
    draft = fixtures.ThoughtsTest.draft
    new = fixtures.ThoughtsTest.new
    save = fixtures.ThoughtsTest.save

    def config(self):
        nodes = []
        edges = []
        for ident, role, content, edge in [('o', 'object', 'screw', 'os'), ('p', 'process', 'fall', 'pf')]:
            nodes.append(dict(id=ident, conceptId=role, contentConceptId=content, value=ident,
                              required=True, included=True, bindingRequired=True, contentEdges=[edge]))
            original = next(e for e in self.state()['edges'] if e['id'] == edge)
            edges.append(dict(id=edge, edgeId=edge, template=signature(original), from_=ident))
            edges[-1].pop('from_')
            edges[-1].update({'from': ident, 'to': ident, 'binding': True, 'required': True,
                             'included': True, 'activation': 'direct'})
        original = next(e for e in self.state()['edges'] if e['id'] == 'op')
        edges.append(dict(id='op', edgeId='op', template=signature(original), required=True,
                          included=True, activation='direct', **{'from': 'o', 'to': 'p'}))
        return dict(nodes=nodes, edges=edges, contexts=[])

    def complete(self):
        d = self.draft()
        self.call('thought_save', draftId=d['id'], anchors=[{'id': 'o', 'start': 0, 'end': 4},
                  {'id': 'p', 'start': 5, 'end': len(d['text'])}])
        self.call('thought_confirm', draftId=d['id'], confirmed=True)
        self.call('thought_complete', draftId=d['id'])

    def test_two_elements_three_real_ordinary_uses_and_roundtrip(self):
        self.save(self.config())
        self.complete()
        scene = self.state()['sceneLab']['scenes'][0]
        self.assertEqual(len(scene['objects']), 2)
        self.assertEqual([o['displayNumber'] for o in scene['objects']], [1, 1])
        facts = scene['entries'][0]['assertions']
        self.assertEqual(len(facts), 3)
        self.assertEqual(sum(f.get('binding', False) for f in facts), 2)
        self.assertEqual(PermanentStore(self.path).read(), self.store.read())
        exported = self.store.export()
        self.assertEqual(exported['version'], 6)
        parse_document(exported)
        wrong = copy.deepcopy(exported)
        wrong['version'] = 5
        with self.assertRaises(Invalid):
            parse_document(wrong)
        self.call('thought_include', draftId=self.draft()['id'], label='Определение')
        target = self.state()['sceneLab']['scenes'][-1]
        self.assertEqual(len(target['objects']), 2)
        self.assertTrue(all(o['contentConceptId'] for o in target['objects']))

    def test_binding_cannot_be_text_or_wrong_endpoints(self):
        for mutate in [lambda c: c['nodes'][0].update(contentConceptId='floor'),
                       lambda c: c['edges'][0].update(binding=False),
                       lambda c: c['nodes'][0].update(contentConceptId='object'),
                       lambda c: c['nodes'][0].update(contentEdges=[])]:
            c = self.config()
            mutate(c)
            with self.assertRaises(Invalid):
                self.save(c)

    def test_content_edges_keep_direct_available_and_context_activation(self):
        c = self.config()
        c['contexts'] = [dict(id='ctx', contextId='permission', template={'id': 'permission', 'from': 'os', 'to': 'pf'},
                              required=False, included=True, **{'from': 'os', 'to': 'pf'})]
        c['edges'][1]['included'] = False
        self.save(c)
        self.assertEqual(continuations(self.draft())[0]['to'], 'pf')
        self.call('thought_step', draftId=self.draft()['id'], targetId='pf', contextId='ctx')
        self.assertEqual(self.draft()['config']['edges'][1]['activation'], 'context')
        self.complete()

    def test_numbers_stable_after_removal_reset_when_empty(self):
        c = self.config()
        extra = copy.deepcopy(c['nodes'][0])
        extra.update(id='o2', contentEdges=['os2'])
        binding = copy.deepcopy(c['edges'][0])
        binding.update(id='os2', **{'from': 'o2', 'to': 'o2'})
        c['nodes'].append(extra)
        c['edges'].append(binding)
        self.save(c)
        self.assertEqual([n['displayNumber'] for n in self.draft()['config']['nodes']], [1, 1, 2])
        c = self.draft()['config']
        c['nodes'] = [n for n in c['nodes'] if n['id'] == 'o2']
        c['edges'] = [e for e in c['edges'] if e['id'] == 'os2']
        self.save(c)
        self.assertEqual(self.draft()['config']['nodes'][0]['displayNumber'], 2)
        self.save({'nodes': [], 'edges': [], 'contexts': []})
        self.save(self.config())
        self.assertEqual(self.draft()['config']['nodes'][0]['displayNumber'], 1)

    def test_primary_span_is_unique(self):
        self.save(self.config())
        with self.assertRaises(Invalid):
            self.save(anchors=[{'id': 'o', 'start': 0, 'end': 4}, {'id': 'p', 'start': 0, 'end': 4}])

    def test_reuse_same_object_new_instance_and_independent_scene(self):
        self.save(self.config())
        self.complete()
        scene = self.state()['sceneLab']['scenes'][0]
        original = next(o for o in scene['objects'] if o['conceptId'] == 'object')
        self.new()
        c = self.config()
        c['nodes'][0].update(sceneObjectId=original['id'], value=original['label'])
        self.save(c)
        self.assertEqual([n['displayNumber'] for n in self.draft()['config']['nodes']], [1, 2])
        self.complete()
        scene = self.state()['sceneLab']['scenes'][0]
        self.assertEqual(len(scene['objects']), 3)
        self.new()
        self.save(self.config())
        self.assertEqual(self.draft()['config']['nodes'][0]['displayNumber'], 2)
        self.call('scene_create', label='Другая', kind='dialogue')
        self.new()
        self.save(self.config())
        self.assertEqual([n['displayNumber'] for n in self.draft()['config']['nodes']], [1, 1])

    def test_v6_import_reset_restore_keep_bound_elements(self):
        self.save(self.config())
        self.complete()
        before = self.store.read()
        exported = self.store.export()
        target = PermanentStore(Path(self.tmp.name) / 'import.sqlite3')
        target.mutate('import', {'document': exported, 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], before['state'])
        preview = prepare(self.state(), {'mode': 'reset', 'selection': []}, before['revision'])[1]
        self.call('manage_apply', mode='reset', selection=[], confirmed=True,
                  previewRevision=preview['revision'], previewHash=preview['hash'])
        self.assertEqual(self.state()['nodes'], [])
        self.call('restore', targetRevision=before['revision'], confirmed=True)
        self.assertEqual(self.state(), before['state'])

    def test_explicit_legacy_binding_compacts_without_losing_use_ids(self):
        c = self.config()
        for n in c['nodes'][:]:
            content = n.pop('contentConceptId')
            c['nodes'].append(dict(id='c-' + n['id'], conceptId=content, value='x', required=False, included=True))
            use = next(e for e in c['edges'] if e['id'] == n['contentEdges'][0])
            use.pop('binding')
            use['to'] = 'c-' + n['id']
        compact, _ = compact_config(c)
        self.assertEqual(len(compact['nodes']), 2)
        self.assertEqual([e['id'] for e in compact['edges']], ['os', 'pf', 'op'])
        self.save(compact)

    def test_new_application_of_legacy_template_uses_compact_contract(self):
        c = self.config()
        for n in c['nodes'][:]:
            content = n.pop('contentConceptId')
            c['nodes'].append(dict(id='c-' + n['id'], conceptId=content, value='x', required=False, included=True))
            use = next(e for e in c['edges'] if e['id'] == n['contentEdges'][0])
            use.pop('binding')
            use['to'] = 'c-' + n['id']
        self.save(c)
        template = self.call('thought_template', draftId=self.draft()['id'], label='Старый явный шаблон')['templateId']
        self.call('thought_new', text='Винт упал', templateId=template, compactElements=True)
        self.assertEqual(len(self.draft()['config']['nodes']), 2)
        self.assertEqual(len(self.draft()['contract']['nodes']), 2)
        self.assertEqual(len(self.state()['thoughtLab']['templates'][0]['config']['nodes']), 4)
        config = self.draft()['config']
        for n in config['nodes']:
            n['value'] = n['id']
        self.save(config)
        self.complete()


if __name__ == '__main__':
    unittest.main()
