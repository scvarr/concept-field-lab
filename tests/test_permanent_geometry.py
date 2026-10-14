import copy
import tempfile
import unittest
from pathlib import Path
from app.permanent import PermanentStore
from app.store import Invalid, Conflict


class PermanentGeometryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PermanentStore(Path(self.temp.name)/'geometry.sqlite3')
        self.call('definition_save', draft={'id':'draft','title':'Раскладка','definition':'Ручная проба','nodes':[{'id':str(i),'existing':False,'designation':'Поле '+str(i)} for i in range(4)],'edges':[{'id':'edge','from':'0','to':'1','existing':False}], 'contextEdges':[], 'routes':[]})
        self.call('definition_publish', draftId='draft', confirmed=True)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, **data):
        return self.store.mutate(action, data, self.store.read()['revision'])

    def apply(self, positions):
        return self.call('layout_apply', positions=positions, algorithm='hierarchical', previewRevision=self.store.read()['revision'], confirmed=True)

    def test_batch_restart_undo_changes_only_coordinates_with_journal(self):
        before = self.store.read()['state']
        positions = {n['id']:{'x':i*100,'y':0} for i,n in enumerate(before['nodes'])}
        self.apply(positions)
        after = self.store.read()['state']
        semantic = copy.deepcopy(after)
        for n, old in zip(semantic['nodes'], before['nodes']): n.update(x=old['x'],y=old['y'])
        self.assertEqual(semantic, before)
        self.store = PermanentStore(self.store.path)
        self.call('layout_restore', confirmed=True)
        self.assertEqual(self.store.read()['state'], before)
        self.assertEqual(self.store.export()['version'], 2)
        with self.assertRaises(Invalid): self.call('layout_restore', confirmed=True)

    def test_pin_stale_overlap_and_manual_move_refusals_are_atomic(self):
        self.call('layout_pin', nodeIds=['0'], pinned=True)
        for payload in [{'positions':{'0':{'x':0,'y':0}},'previewRevision':self.store.read()['revision']}, {'positions':{'1':{'x':0,'y':0}},'previewRevision':-1}, {'positions':{'1':{'x':520,'y':220}},'previewRevision':self.store.read()['revision']}]:
            before=self.store.read()
            with self.assertRaises((Invalid,Conflict)): self.call('layout_apply', algorithm='force',confirmed=True,**payload)
            self.assertEqual(self.store.read(),before)
        self.call('layout_pin', nodeIds=['0'], pinned=False)
        self.apply({str(i):{'x':i*100,'y':0} for i in range(4)})
        self.call('position', nodeId='1', x=150, y=0)
        before=self.store.read()
        with self.assertRaises(Invalid): self.call('layout_restore',confirmed=True)
        self.assertEqual(self.store.read(),before)

    def test_confirmed_geometry_and_pin_export_import(self):
        before=self.store.read()
        with self.assertRaises(Invalid): self.call('layout_apply',positions={'0':{'x':0,'y':0}},algorithm='force',previewRevision=before['revision'])
        self.call('layout_pin',nodeIds=['0'],pinned=True)
        document=self.store.export();target=PermanentStore(Path(self.temp.name)/'import.sqlite3')
        target.mutate('import',{'document':document,'confirmed':True},0)
        self.assertEqual(target.read()['state'],self.store.read()['state'])

    def test_undo_preserves_independent_designation_edit(self):
        before=self.store.read()['state']
        self.apply({str(i):{'x':i*100,'y':0} for i in range(4)})
        self.call('designation_save',nodeId='0',text='Новое обозначение после раскладки')
        mappings=copy.deepcopy(self.store.read()['state']['designations'])
        self.call('layout_restore',confirmed=True)
        after=self.store.read()['state']
        self.assertEqual(after['designations'],mappings)
        self.assertEqual(after['nodes'],before['nodes'])
