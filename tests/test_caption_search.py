import copy
import unittest
from app.dictionary import search
from app.permanent import empty_graph


class CaptionSearchTest(unittest.TestCase):
    def test_anonymous_nested_alpha_searches_all_component_designations_without_writes(self):
        graph = empty_graph()
        graph['nodes'] = [{'id': name, 'label': '', 'structure': structure} for name, structure in [('outer', 'alpha'), ('inner', 'alpha'), ('head', 'concept'), ('named', 'alpha')]]
        graph['edges'] = [{'id': str(i), 'from': a, 'to': b, 'role': role} for i, (a, b, role) in enumerate([('outer', 'inner', 'component'), ('inner', 'head', 'component'), ('named', 'inner', 'component'), ('head', 'named', 'relation')])]
        graph['designations'] = [{'target': 'head', 'text': 'Головка'}, {'target': 'head', 'text': 'Шляпка'}, {'target': 'named', 'text': 'Винт'}]
        before = copy.deepcopy(graph)
        for query in ['головка', 'шляпка']:
            result = search(graph, query)
            self.assertEqual({r['nodeId'] for r in result['concepts']}, {'head', 'inner', 'outer'})
            self.assertEqual(next(r for r in result['concepts'] if r['nodeId'] == 'inner')['labels'], [])
        graph['edges'] = [e for e in graph['edges'] if e['from'] != 'outer']
        self.assertNotIn('outer', {r['nodeId'] for r in search(graph, 'головка')['concepts']})
        graph['edges'] = before['edges']
        self.assertEqual(graph, before)
        result=search(graph,'Головка')
        self.assertEqual(result['concepts'][0]['nodeId'],'head')
