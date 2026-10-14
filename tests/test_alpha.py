import copy
import tempfile
import unittest
from pathlib import Path
from app.builder import prepare
from app.permanent import PermanentStore, parse_document, validate_graph
from app.store import Invalid, uid
from app.journal import expand_history


class AlphaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'alpha.sqlite3'
        self.store = PermanentStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])

    def node(self, text='', alpha=False):
        return {'id': uid(), 'existing': False, 'designation': text,
                'designations': [{'id': uid(), 'text': text}] if text else [],
                **({'structure': 'alpha'} if alpha else {})}

    def existing(self, node):
        actual = next(n for n in self.store.read()['state']['nodes'] if n['id'] == node['id'])
        return {'id': actual['id'], 'existing': True, 'base': copy.deepcopy(actual)}

    def edge(self, source, target, role='component'):
        return {'id': uid(), 'from': source['id'], 'to': target['id'], 'role': role, 'existing': False}

    def draft(self, nodes, edges):
        return {'id': uid(), 'title': 'Проверка α', 'definition': 'Ручная составная структура',
                'nodes': nodes, 'edges': edges, 'contextEdges': [], 'routes': []}

    def publish(self, draft):
        self.call('definition_save', draft=draft)
        return self.call('definition_publish', draftId=draft['id'], confirmed=True)

    def fixture(self):
        rod, head, turn, a2 = self.node('Стержень'), self.node('Головка'), self.node('Завинчивание'), self.node(alpha=True)
        inner = self.draft([a2, rod, head, turn], [self.edge(a2, rod), self.edge(a2, head), self.edge(head, turn, 'relation')])
        self.publish(inner)
        part, a1, property_node = self.node('Деталь'), self.node(alpha=True), self.node('Характеристика целого')
        outer = self.draft([a1, part, self.existing(a2), property_node], [self.edge(a1, part), self.edge(a1, a2), self.edge(a1, property_node, 'relation')])
        self.publish(outer)
        self.call('designation_save', nodeId=a1['id'], text='винт')
        return inner, outer, a1, a2, head

    def test_nested_reuse_restart_import_history_and_restore(self):
        inner, outer, a1, a2, head = self.fixture()
        before = self.store.read()
        other = self.node(alpha=True)
        reuse = self.draft([other, self.existing(a2)], [self.edge(other, a2)])
        self.publish(reuse)
        state = self.store.read()['state']
        self.assertEqual(len([n for n in state['nodes'] if n['id'] == a2['id']]), 1)
        self.assertEqual([e['to'] for e in state['edges'] if e['from'] == a1['id'] and e['role'] == 'component'], [outer['nodes'][1]['id'], a2['id']])
        self.assertFalse(any(e['from'] == a1['id'] and e['to'] == inner['nodes'][3]['id'] for e in state['edges']))
        document = self.store.export()
        self.assertEqual(document['version'], 2)
        self.assertEqual(PermanentStore(self.path).export()['history'], document['history'])
        target = PermanentStore(Path(self.temp.name) / 'import.sqlite3')
        target.mutate('import', {'document': document, 'confirmed': True}, 0)
        self.assertEqual(target.read()['state'], state)
        self.assertEqual(target.export()['importedHistory'][0]['history'], document['history'])
        self.assertEqual(list(expand_history(document))[-1]['state'], state)
        revision = target.read()['revision']
        target.mutate('import', {'document': document, 'confirmed': True}, revision)
        self.assertEqual(target.read()['revision'], revision)
        self.call('restore', targetRevision=before['revision'], confirmed=True)
        self.assertEqual(self.store.read()['state'], before['state'])

    def test_edit_membership_and_characteristics_stable_ids_and_protection(self):
        inner, outer, a1, a2, head = self.fixture()
        old_edges = [e['id'] for e in inner['edges']]
        inner['nodes'][0].update(kind='Собственная характеристика', notes='Без наследования')
        extra = self.node('Дополнительный компонент')
        inner['nodes'].append(extra); inner['edges'].append(self.edge(a2, extra))
        self.publish(inner)
        state = self.store.read()['state']
        alpha = next(n for n in state['nodes'] if n['id'] == a2['id'])
        self.assertEqual(alpha['kind'], 'Собственная характеристика')
        self.assertTrue(set(old_edges) <= {e['id'] for e in state['edges']})
        stale = copy.deepcopy(outer)
        self.call('definition_save', draft=stale)
        before = self.store.read()
        with self.assertRaises(Invalid): self.call('definition_publish', draftId=outer['id'], confirmed=True)
        self.assertEqual(self.store.read(), before)
        # Removing a node used by another definition must roll back atomically.
        bad = copy.deepcopy(inner)
        bad['nodes'] = [n for n in bad['nodes'] if n['id'] != a2['id']]
        bad['edges'] = [e for e in bad['edges'] if e['from'] != a2['id']]
        with self.assertRaises(Invalid): prepare(state, bad)

    def test_incomplete_draft_empty_alpha_and_cycle_rejected_atomically(self):
        a, b = self.node(alpha=True), self.node(alpha=True)
        draft = self.draft([a, b], [])
        self.call('definition_save', draft=draft)
        before = self.store.read()
        with self.assertRaises(Invalid): self.call('definition_publish', draftId=draft['id'], confirmed=True)
        self.assertEqual(self.store.read(), before)
        malformed = copy.deepcopy(draft);malformed['nodes'][0].update(existing=True, base=7)
        with self.assertRaises(Invalid): self.call('definition_save', draft=malformed)
        for edges in ([self.edge(a, a)], [self.edge(a, b), self.edge(b, a)], [self.edge(a, b), self.edge(a, b)]):
            bad = copy.deepcopy(draft);bad['edges'] = edges
            with self.assertRaises(Invalid): self.call('definition_save', draft=bad)
            self.assertEqual(self.store.read(), before)

    def test_cross_definition_cycle_dangling_import_and_invalid_roles(self):
        inner, outer, a1, a2, head = self.fixture()
        state = self.store.read()['state']
        bad = copy.deepcopy(inner);bad['nodes'].append(self.existing(a1));bad['edges'].append(self.edge(a2, a1))
        with self.assertRaises(Invalid): prepare(state, bad)
        variants = []
        for role in ('unknown', 'component'):
            broken = copy.deepcopy(state);next(e for e in broken['edges'] if e['from'] == head['id'])['role'] = role;variants.append(broken)
        broken = copy.deepcopy(state);broken['edges'][0]['to'] = uid();variants.append(broken)
        broken = copy.deepcopy(state);broken['edges'][0]['from'] = head['id'];variants.append(broken)
        broken = copy.deepcopy(state);broken['nodes'][0]['structure'] = 'combination';variants.append(broken)
        for broken in variants:
            document = {'format': 'concept-field-permanent', 'version': 2, 'kind': 'graph', 'state': broken}
            before = self.store.read()
            with self.assertRaises(Invalid): self.call('import', document=document, confirmed=True)
            self.assertEqual(self.store.read(), before)

    def test_component_cannot_enter_route_or_context(self):
        a, b, c = self.node(alpha=True), self.node('b'), self.node('c')
        edge, relation = self.edge(a, b), self.edge(b, c, 'relation')
        draft = self.draft([a, b, c], [edge, relation])
        for key, rows in [('routes', [{'id': uid(), 'edgeIds': [edge['id'], relation['id']]}]),
                          ('contextEdges', [{'id': uid(), 'from': edge['id'], 'to': relation['id']}])]:
            bad = copy.deepcopy(draft);bad[key] = rows
            with self.assertRaises(Invalid): self.call('definition_save', draft=bad)

    def test_v1_graph_and_history_remain_valid_without_migration(self):
        node = self.node('Прежний концепт');self.publish(self.draft([node], []))
        document = self.store.export();document['version'] = 1
        self.assertEqual(parse_document(document), document['state'])
        self.assertEqual(PermanentStore(self.path).read(), self.store.read())

    def test_history_validation_version_and_component_reference_protection(self):
        inner, outer, a1, a2, head = self.fixture()
        document = self.store.export()
        bad = copy.deepcopy(document);bad['version'] = 1
        with self.assertRaises(Invalid): parse_document(bad)
        bad = copy.deepcopy(document);bad['history'][0]['state'] = {**copy.deepcopy(document['state']), 'nodes': [{'id': uid()}]}
        with self.assertRaises(Invalid): parse_document(bad)
        component = inner['edges'][0]
        reuse = self.draft([self.existing(a2), self.existing(inner['nodes'][1])], [{**component, 'existing': True}])
        self.publish(reuse)
        state = self.store.read()['state']
        self.assertEqual(state['definitionPublications'][reuse['id']]['componentIds'], [component['id']])
        bad = copy.deepcopy(inner);bad['edges'] = [e for e in bad['edges'] if e['id'] != component['id']]
        with self.assertRaises(Invalid): prepare(state, bad)

    def test_deep_structure_validation_is_iterative(self):
        from app.alpha import validate_structure
        nodes = [{'id': str(i), 'structure': 'alpha' if i < 1499 else 'concept'} for i in range(1500)]
        edges = [{'from': str(i), 'to': str(i+1), 'role': 'component'} for i in range(1499)]
        validate_structure(nodes, edges)
        edges.append({'from': '1498', 'to': '0', 'role': 'component'})
        with self.assertRaises(Invalid): validate_structure(nodes, edges)
