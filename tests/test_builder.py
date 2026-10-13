"""ID integrity, negative routes, conservative edits and legacy preservation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from app.store import Store, Invalid, Conflict, uid, validate
from app.builder import prepare, validate_draft
from app.dictionary import search
from app.exchange import graph_export, parse_document


class BuilderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'workspace.sqlite3')
        self.call('create_study', {'title': 'Исходный', 'label': 'деталь'})
        source = self.store.read()['state']['studies'][0]
        self.source = copy.deepcopy(source)
        result = self.call('create_accumulation', {'title': 'Полотно', 'sourceStudyIds': [source['id']]})
        self.sid = result['result']['studyId']

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, data):
        return self.store.mutate(action, data, self.store.read()['revision'])

    def canvas(self):
        return next(s for s in self.store.read()['state']['studies'] if s['id'] == self.sid)

    def draft(self):
        s = self.canvas()
        detail = s['nodes'][0]
        nodes = [{'id': uid(), 'designation': term, 'existing': False} for term in ('гайка', 'крепёжный', 'резьба', 'внутренний')]
        nodes.insert(2, {'id': detail['id'], 'designation': 'деталь', 'existing': True, 'base': copy.deepcopy(detail)})
        edges = [{'id': uid(), 'from': nodes[a]['id'], 'to': nodes[b]['id'], 'existing': False} for a, b in ((0, 1), (1, 2), (2, 3), (2, 4))]
        return {'id': uid(), 'title': 'Гайка', 'definition': 'Гайка — крепёжная деталь с внутренней резьбой.',
                'nodes': nodes, 'edges': edges, 'contextEdges': [{'id': uid(), 'from': edges[a]['id'], 'to': edges[b]['id']} for a, b in ((0, 1), (0, 2), (1, 2))],
                'routes': [{'id': uid(), 'edgeIds': [e['id'] for e in edges[:3]]}]}

    def save(self, draft):
        self.call('definition_save', {'studyId': self.sid, 'draft': draft})

    def publish(self, draft):
        return self.call('definition_publish', {'studyId': self.sid, 'draftId': draft['id'], 'confirmed': True})

    def test_dictionary_all_pos_and_no_graph_nodes(self):
        before = self.store.read()
        for term, pos in [('гайка', 'NOUN'), ('крепёжный', 'ADJF'), ('внутренний', 'ADJF'), ('резьба', 'NOUN'), ('соединять', 'INFN'), ('внутри', 'ADVB'), ('с', 'PREP')]:
            result = search(before['state'], term, self.sid)
            self.assertTrue(any(w['lemma'] == term and pos in w['grammemes'] for w in result['words']), (term, result['words']))
        result = search(before['state'], 'деталь', self.sid)
        self.assertEqual({c['location'] for c in result['concepts']}, {'source', 'canvas'})
        self.assertTrue(result['multipleConcepts'])
        self.assertEqual(self.store.read(), before)

    def test_reused_edge_publication_protected_even_without_new_objects(self):
        draft = self.draft()
        self.save(draft)
        self.publish(draft)
        other = {'id': uid(), 'title': 'Reuse', 'definition': 'Явное повторное использование', 'nodes': [], 'edges': [], 'routes': [], 'contextEdges': []}
        edge = draft['edges'][0]
        for n in self.canvas()['nodes']:
            if n['id'] in (edge['from'], edge['to']):
                other['nodes'].append({'id': n['id'], 'existing': True, 'designation': '', 'base': n})
        other['edges'] = [{**edge, 'existing': True}]
        self.save(other)
        self.publish(other)
        from app.accumulation import neighbourhood
        view = neighbourhood(self.canvas(), edge['from'])
        self.assertTrue(any(p['sourceId'] == other['id'] for p in view['sourceCounts']))
        draft['edges'] = draft['edges'][1:]
        draft['contextEdges'] = []
        draft['routes'] = []
        self.save(draft)
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.publish(draft)
        self.assertEqual(before, self.store.read())

    def test_preview_commit_reopen_branch_and_reuse(self):
        before = self.canvas()
        draft = self.draft()
        self.save(draft)
        self.assertEqual(self.canvas()['nodes'], before['nodes'])
        self.assertEqual(self.canvas()['edges'], before['edges'])
        preview_study, preview = prepare(self.canvas(), draft)
        self.publish(draft)
        after = self.canvas()
        self.assertEqual(after, preview_study)
        self.assertEqual(after['accumulation']['sources'], before['accumulation']['sources'])
        self.assertEqual(after['accumulation']['decisions'], before['accumulation']['decisions'])
        self.assertEqual(len(after['nodes']), 5)
        self.assertEqual(len(after['edges']), 4)
        contexts = after['accumulation']['manual']['contextEdges']
        self.assertEqual(len(contexts), 3)
        self.assertFalse(any(c['from'] == draft['edges'][3]['id'] or c['to'] == draft['edges'][3]['id'] for c in contexts))
        self.assertTrue(all(n['label'] == '' and n['kind'] == '' for n in after['accumulation']['manual']['nodes']))
        self.publish(draft)
        self.assertEqual(self.canvas(), after)
        reloaded = Store(self.store.path)
        self.assertEqual(reloaded.read()['state'], self.store.read()['state'])
        next_draft = {'id': uid(), 'title': 'Следующее определение', 'definition': 'Ручной следующий ввод', 'nodes': [], 'edges': [], 'contextEdges': [], 'routes': []}
        for n in draft['nodes'][:2]:
            actual = next(v for v in after['nodes'] if v['id'] == n['id'])
            next_draft['nodes'].append({'id': n['id'], 'existing': True, 'designation': n['designation'], 'base': actual})
        next_draft['edges'] = [{**draft['edges'][0], 'existing': True}]
        self.save(next_draft)
        self.publish(next_draft)
        self.assertEqual(self.canvas()['edges'], after['edges'])
        self.assertEqual(len(self.canvas()['nodes']), 5)
        result = search(self.store.read()['state'], 'гайка', self.sid)
        found = next(c for c in result['concepts'] if c['nodeId'] == draft['nodes'][0]['id'])
        self.assertEqual(found['edges'][0]['id'], draft['edges'][0]['id'])
        self.assertTrue(found['contexts'])

    def test_v4_export_import_exact_and_legacy_unchanged(self):
        draft = self.draft()
        self.save(draft)
        self.publish(draft)
        document = graph_export(self.store, self.sid)
        self.assertEqual(document['version'], 4)
        other = Store(Path(self.temp.name) / 'other.sqlite3')
        staged = other.mutate('import', {'document': document}, 0)
        ids = [p['id'] for p in staged['state']['proposals'] if p['status'] == 'pending']
        other.mutate('review_proposals', {'proposalIds': ids, 'decision': 'accept'}, staged['revision'])
        self.assertEqual(other.read()['state']['studies'][0], self.canvas())
        staged = other.mutate('import', {'document': document}, other.read()['revision'])
        self.assertEqual(staged['result']['added'], 0)
        self.assertEqual(self.store.read()['state']['studies'][0], self.source)
        bad = copy.deepcopy(document)
        bad['version'] = 3
        with self.assertRaises(Invalid):
            parse_document(bad)

    def test_route_context_invalid_and_failed_write_atomic(self):
        draft = self.draft()
        bad = copy.deepcopy(draft)
        bad['routes'][0]['edgeIds'] = [draft['edges'][2]['id'], draft['edges'][0]['id']]
        with self.assertRaises(Invalid):
            validate_draft(bad)
        for change in ('dangling', 'same', 'duplicate'):
            bad = copy.deepcopy(draft)
            if change == 'dangling':
                bad['contextEdges'][0]['to'] = uid()
            elif change == 'same':
                bad['contextEdges'][0]['to'] = bad['contextEdges'][0]['from']
            else:
                bad['contextEdges'].append({**bad['contextEdges'][0], 'id': uid()})
            before = self.store.read()
            with self.assertRaises(Invalid):
                self.save(bad)
            self.assertEqual(before, self.store.read())
        self.save(draft)
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.call('definition_publish', {'studyId': self.sid, 'draftId': draft['id']})
        with self.assertRaises(Conflict):
            self.store.mutate('definition_publish', {'studyId': self.sid, 'draftId': draft['id'], 'confirmed': True}, 0)
        self.assertEqual(before, self.store.read())

    def test_edit_own_definition_and_refuse_damage_to_another(self):
        draft = self.draft()
        self.save(draft)
        self.publish(draft)
        draft['nodes'][0]['designation'] = 'гайка (обозначение)'
        draft['contextEdges'][0]['from'], draft['contextEdges'][0]['to'] = draft['contextEdges'][0]['to'], draft['contextEdges'][0]['from']
        self.save(draft)
        self.publish(draft)
        self.assertEqual(self.canvas()['designations'][-4]['text'], 'гайка (обозначение)')
        other = self.draft()
        actual = next(n for n in self.canvas()['nodes'] if n['id'] == draft['nodes'][0]['id'])
        other['nodes'][0] = {'id': actual['id'], 'existing': True, 'designation': 'гайка', 'base': actual}
        other['edges'][0]['from'] = actual['id']
        self.save(other)
        self.publish(other)
        draft['nodes'] = draft['nodes'][1:]
        draft['edges'] = draft['edges'][1:]
        draft['contextEdges'] = [c for c in draft['contextEdges'] if draft['edges'][0]['id'] in (c['from'], c['to']) and c['from'] != other['edges'][0]['id']]
        draft['contextEdges'] = []
        draft['routes'] = []
        self.save(draft)
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.publish(draft)
        self.assertEqual(self.store.read(), before)

    def test_parallel_edge_requires_reason_and_stale_node_refused(self):
        draft = self.draft()
        self.save(draft)
        self.publish(draft)
        other = {'id': uid(), 'title': 'Проба', 'definition': 'Проба', 'nodes': [], 'edges': [], 'routes': [], 'contextEdges': []}
        for n in self.canvas()['nodes'][:2]:
            other['nodes'].append({'id': n['id'], 'existing': True, 'designation': '', 'base': n})
        e = draft['edges'][0]
        ids = (e['from'], e['to'])
        other['nodes'] = [{'id': n['id'], 'existing': True, 'designation': '', 'base': n} for n in self.canvas()['nodes'] if n['id'] in ids]
        other['edges'] = [{'id': uid(), 'from': e['from'], 'to': e['to'], 'existing': False}]
        self.save(other)
        with self.assertRaises(Invalid):
            self.publish(other)
        other['edges'][0]['parallelReason'] = 'Оператор различает два утверждения'
        self.save(other)
        self.publish(other)
        other['nodes'][0]['base']['notes'] = 'Устаревшее содержание'
        self.save(other)
        with self.assertRaises(Invalid):
            self.publish(other)
