"""Geometry commits preserve semantic materialization and complete hidden sets."""
import copy
import tempfile
import unittest
from pathlib import Path

from app.store import Store, Invalid, Conflict, validate
from app.exchange import graph_export
from scripts.accumulation_fixture import synthetic, large, accept


class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/"workspace.sqlite3")
        self.a = synthetic(self.store, "Источник A")
        self.b = synthetic(self.store, "Источник B")
        self.sid = self.act("create_accumulation", title="Geometry", sourceStudyIds=[self.a["studyId"], self.b["studyId"]])["studyId"]

    def tearDown(self):
        self.tmp.cleanup()

    def act(self, action, **data):
        return self.store.mutate(action, data, self.store.read()["revision"])["result"]

    def study(self):
        return next(s for s in self.store.read()["state"]["studies"] if s["id"] == self.sid)

    def move(self, ids=None):
        return {n["id"]: {"x": n["x"]+37, "y": n["y"]+91} for n in self.study()["nodes"] if ids is None or n["id"] in ids}

    def test_batch_partial_undo_preserves_semantics_and_single_revision(self):
        before = self.store.read()
        study = self.study()
        ids = [n["id"] for n in study["nodes"]][::2]
        self.act("layout_positions", studyId=self.sid, positions=self.move(ids), algorithm="force")
        after = self.store.read()
        self.assertEqual(after["revision"], before["revision"]+1)
        self.assertEqual(after["state"]["matches"], before["state"]["matches"])
        expected = copy.deepcopy(study)
        for n in expected["nodes"]:
            if n["id"] in ids:
                n["x"]+=37; n["y"]+=91
        actual = self.study(); actual["accumulation"].pop("lastLayout")
        self.assertEqual(actual, expected)
        self.act("layout_restore", studyId=self.sid)
        self.assertEqual(self.study(), study)
        # Both applied and undone versions remain in the standard journal.
        self.assertEqual(self.store.history()[0]["action"], "layout_restore")

    def test_layout_does_not_reset_operator_decisions_or_matches(self):
        self.act("match", leftStudy=self.a["studyId"], leftNode=self.a["shared"], rightStudy=self.b["studyId"], rightNode=self.b["shared"], status="confirmed", reason="Синтетическая проверка")
        nodes=self.study()["nodes"]
        self.act("accumulation_decide", studyId=self.sid, leftNode=nodes[0]["id"], rightNode=nodes[4]["id"], status="confirmed", reason="Синтетическая проверка")
        self.act("accumulation_decide", studyId=self.sid, leftNode=nodes[1]["id"], rightNode=nodes[5]["id"], status="rejected", reason="Синтетическая проверка")
        before=self.store.read()
        self.act("layout_positions", studyId=self.sid, positions=self.move(), algorithm="force")
        self.assertEqual(self.store.read()["state"]["matches"],before["state"]["matches"])
        previous=next(s for s in before["state"]["studies"] if s["id"]==self.sid)
        self.assertEqual(self.study()["accumulation"]["decisions"],previous["accumulation"]["decisions"])
        self.assertEqual(self.study()["edges"],previous["edges"])

    def test_pin_survives_source_projection_and_roundtrip(self):
        nid = self.study()["nodes"][0]["id"]
        self.act("layout_pin", studyId=self.sid, nodeIds=[nid], pinned=True)
        pinned = self.study()["nodes"][0]
        c = synthetic(self.store, "Источник C")
        self.act("accumulation_add_source", studyId=self.sid, sourceStudyId=c["studyId"])
        self.assertEqual(self.study()["nodes"][0], pinned)
        self.act("layout_positions", studyId=self.sid, positions=self.move([n["id"] for n in self.study()["nodes"] if n["id"] != nid]), algorithm="radial")
        doc = graph_export(self.store, self.sid)
        other = Store(Path(self.tmp.name)/"import.sqlite3")
        accept(other, doc)
        self.assertEqual(other.read()["state"]["studies"][0], self.study())
        self.act("layout_pin", studyId=self.sid, nodeIds=[nid], pinned=False)
        self.assertNotIn("layoutPinned", self.study()["nodes"][0])

    def test_invalid_batch_pin_and_stale_revision_are_atomic(self):
        nid = self.study()["nodes"][0]["id"]
        self.act("layout_pin", studyId=self.sid, nodeIds=[nid], pinned=True)
        before = self.store.read()
        bad = [self.move(), {"missing": {"x":0,"y":0}}, {nid:{"x":True,"y":0}}, {nid:{"x":float('nan'),"y":0}}, {nid:{"x":0,"y":0,"notes":"bad"}}, {}]
        for positions in bad:
            with self.assertRaises(Invalid):
                self.act("layout_positions", studyId=self.sid, positions=positions, algorithm="force")
            self.assertEqual(self.store.read(), before)
        with self.assertRaises(Conflict):
            self.store.mutate("layout_positions", {"studyId":self.sid,"positions":self.move(),"algorithm":"force"}, before["revision"]-1)
        self.assertEqual(self.store.read(), before)

    def test_undo_refuses_intervening_move_and_history_restores_geometry(self):
        before = self.store.read()
        self.act("layout_positions", studyId=self.sid, positions=self.move(), algorithm="hierarchical")
        nid = self.study()["nodes"][0]["id"]
        self.act("position", studyId=self.sid, nodeId=nid, x=1, y=2)
        changed = self.store.read()
        with self.assertRaises(Invalid):
            self.act("layout_restore", studyId=self.sid)
        self.assertEqual(self.store.read(), changed)
        self.act("restore", targetRevision=before["revision"])
        self.assertEqual(self.store.read()["state"], before["state"])

    def test_full_2004_nodes_one_transaction_and_no_lost_sources(self):
        big = large(self.store, 2000)
        self.sid = self.act("create_accumulation", title="2004 / 3001", sourceStudyIds=[self.a["studyId"], big["studyId"]])["studyId"]
        original = self.study()
        self.assertEqual((len(original["nodes"]),len(original["edges"])),(2004,3001))
        before = self.store.read()["revision"]
        result = self.act("layout_positions", studyId=self.sid, positions=self.move(), algorithm="force")
        self.assertEqual(result["count"],2004)
        self.assertEqual(self.store.read()["revision"], before+1)
        self.assertEqual(self.study()["edges"], original["edges"])
        self.assertEqual(self.study()["accumulation"]["sources"], original["accumulation"]["sources"])
        self.act("layout_restore", studyId=self.sid)
        self.assertEqual(self.study(), original)

    def test_import_rejects_invalid_pin_and_undo_coordinates(self):
        self.act("layout_positions", studyId=self.sid, positions=self.move(), algorithm="force")
        state = self.store.read()["state"]
        for tweak in (lambda s:s["nodes"][0].update(layoutPinned="yes"),lambda s:s["accumulation"]["lastLayout"]["before"].update(extra={"x":0,"y":0})):
            bad=copy.deepcopy(state);s=next(s for s in bad["studies"] if s["id"]==self.sid);tweak(s)
            with self.assertRaises(Invalid):validate(bad)
