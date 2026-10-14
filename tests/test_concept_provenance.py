import copy
import unittest
from tests import test_permanent


class ConceptProvenanceTest(unittest.TestCase):
    setUp = test_permanent.PermanentTest.setUp
    tearDown = test_permanent.PermanentTest.tearDown
    call = test_permanent.PermanentTest.call
    draft = test_permanent.PermanentTest.draft
    publish = test_permanent.PermanentTest.publish
    def test_republication_preserves_creation_and_missing_origin(self):
        draft = self.draft()
        draft['source'] = {'name': 'Синтетический первичный источник'}
        self.publish(draft)
        origins = copy.deepcopy(self.store.read()['state']['nodes'][0]['origins'])
        draft['definition'] = 'Изменённое опубликованное определение'
        draft['source'] = {'name': 'Другой источник новой редакции'}
        self.publish(draft)
        state = self.store.read()['state']
        self.assertEqual(state['nodes'][0]['origins'], origins)
        self.assertEqual(state['definitionPublications'][draft['id']]['definition'], draft['definition'])
        document = self.store.export()
        document.pop('history')
        document.pop('historyEncoding')
        document['state']['nodes'][0]['origins'] = []
        from app.permanent import PermanentStore
        other = PermanentStore(self.path.parent / 'missing.sqlite3')
        other.mutate('import', {'document': document, 'confirmed': True}, 0)
        other.mutate('definition_publish', {'draftId': draft['id'], 'confirmed': True}, other.read()['revision'])
        self.assertEqual(other.read()['state']['nodes'][0]['origins'], [])
