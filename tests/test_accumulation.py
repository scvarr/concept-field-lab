"""M005: persistence and provenance mechanics, using synthetic judgments only."""
import copy
import tempfile
import unittest
from pathlib import Path

from app.accumulation import lexical_index, neighbourhood, reference
from app.exchange import graph_export, parse_document
from app.store import Store, Invalid, validate


class AccumulationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "workspace.sqlite3")
        self.a = self.source("A")
        self.b = self.source("B")
        made = self.act("create_accumulation", title="Синтетическое полотно", sourceStudyIds=[self.a["sid"], self.b["sid"]])
        self.sid = made["studyId"]

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, **data):
        return self.store.mutate(action, data, self.store.read()["revision"])["result"]

    def source(self, title):
        made = self.act("create_study", title=title, label="корень" + title)
        sid = made["studyId"]
        common = self.act("add_node", studyId=sid, label="общее")["nodeId"]
        disputed = self.act("add_node", studyId=sid, label="спорное")["nodeId"]
        for nid, word in ((common, "словарное"), (disputed, "отказ")):
            self.act("add_designation", studyId=sid, target=nid, text=word)
        self.act("add_edge", studyId=sid, **{"from": made["nodeId"], "to": common, "type": "исходное-" + title})
        self.act("add_edge", studyId=sid, **{"from": common, "to": disputed, "type": "уточнение-" + title})
        return {"sid": sid, "root": made["nodeId"], "common": common, "disputed": disputed}

    def study(self):
        return next(s for s in self.store.read()["state"]["studies"] if s["id"] == self.sid)

    def local(self, source, key):
        ref = reference(source["sid"], source[key])
        from app.accumulation import partition
        return partition(self.study()["accumulation"])[1][ref]

    def decide(self, left, right, status):
        return self.act("accumulation_decide", studyId=self.sid, leftNode=left, rightNode=right,
                        status=status, reason="Синтетическая проверка, не семантическое утверждение")

    def test_independent_blocks_and_separate_lexical_sources(self):
        s = self.study()
        self.assertEqual((len(s["nodes"]), len(s["edges"]), len(s["rootIds"])), (6, 4, 2))
        self.assertEqual(len(lexical_index(s)["candidates"]), 2)
        self.assertEqual({g["term"] for g in lexical_index(s)["groups"]}, {"словарное", "отказ"})
        self.assertEqual({g["term"] for g in lexical_index(s, "label")["groups"]}, {"общее", "спорное"})
        self.assertEqual({g["basis"] for g in lexical_index(s, "both")["groups"]}, {"designation", "label"})
        self.assertTrue(all(c["visualOnly"] for c in lexical_index(s)["candidates"]))
        self.assertFalse(self.store.read()["state"]["matches"])
        for source in s["accumulation"]["sources"]:
            self.assertEqual(source["snapshot"], next(x for x in self.store.read()["state"]["studies"] if x["id"] == source["studyId"]))

    def test_merge_preserves_every_edge_and_original_presentation(self):
        before = copy.deepcopy(self.study())
        left, right = self.local(self.a,"common"), self.local(self.b,"common")
        self.decide(left, right, "confirmed")
        after = self.study()
        self.assertEqual(len(after["nodes"]), 5)
        self.assertEqual({e["id"] for e in after["edges"]}, {e["id"] for e in before["edges"]})
        merged = next(n for n in after["nodes"] if n["id"] == left)
        self.assertEqual(len(merged["origins"]), 2)
        self.assertEqual((merged["x"],merged["y"]), next((n["x"],n["y"]) for n in before["nodes"] if n["id"] == left))
        for edge in after["edges"]:
            old = next(e for e in before["edges"] if e["id"] == edge["id"])
            self.assertEqual(edge["type"], old["type"])
            self.assertEqual(edge["origins"], old["origins"])
            self.assertEqual(edge["accumulationSourceId"], old["accumulationSourceId"])
        g = next(g for g in lexical_index(after)["groups"] if g["term"] == "словарное")
        self.assertEqual((g["nodes"], g["representations"], g["counts"]["confirmed"]), (1,2,1))

    def test_parallel_edges_never_coalesce_and_direction_survives(self):
        self.decide(self.local(self.a,"common"),self.local(self.b,"common"),"confirmed")
        self.decide(self.local(self.a,"disputed"),self.local(self.b,"disputed"),"confirmed")
        rows = [e for e in self.study()["edges"] if e["type"].startswith("уточнение")]
        self.assertEqual(len(rows),2)
        self.assertEqual((rows[0]["from"],rows[0]["to"]),(rows[1]["from"],rows[1]["to"]))
        self.assertNotEqual(rows[0]["id"],rows[1]["id"])
        self.assertFalse(lexical_index(self.study())["candidates"])

    def test_pending_rejected_and_next_source_preserve_decisions_positions_camera(self):
        self.decide(self.local(self.a,"common"),self.local(self.b,"common"),"pending")
        self.assertEqual(len(lexical_index(self.study())["candidates"]),2)
        self.decide(self.local(self.a,"common"),self.local(self.b,"common"),"confirmed")
        self.decide(self.local(self.a,"disputed"),self.local(self.b,"disputed"),"rejected")
        self.assertFalse(lexical_index(self.study())["candidates"])
        self.act("accumulation_camera",studyId=self.sid,camera={"x":450,"y":-100,"scale":.7})
        old = copy.deepcopy(self.study())
        c = self.source("C")
        self.act("accumulation_add_source",studyId=self.sid,sourceStudyId=c["sid"])
        new = self.study()
        self.assertEqual(len(new["rootIds"]),3)
        self.assertEqual(new["accumulation"]["decisions"],old["accumulation"]["decisions"])
        self.assertEqual(new["accumulation"]["camera"],old["accumulation"]["camera"])
        self.assertEqual([(n["id"],n["x"],n["y"]) for n in new["nodes"][:len(old["nodes"])]],[(n["id"],n["x"],n["y"]) for n in old["nodes"]])
        self.assertEqual(len(lexical_index(new)["candidates"]),3)
        self.assertEqual(len(lexical_index(new,status="rejected")["groups"]),1)

    def test_transitive_refusal_is_atomic(self):
        self.decide(self.local(self.a,"disputed"),self.local(self.b,"disputed"),"rejected")
        c = self.source("C")
        self.act("accumulation_add_source",studyId=self.sid,sourceStudyId=c["sid"])
        self.decide(self.local(self.a,"disputed"),self.local(c,"disputed"),"confirmed")
        before = self.store.read()
        with self.assertRaisesRegex(Invalid,"противоречит"):
            self.decide(self.local(c,"disputed"),self.local(self.b,"disputed"),"confirmed")
        self.assertEqual(self.store.read(),before)
        with self.assertRaisesRegex(Invalid,"Неопределённость"):
            self.decide(self.local(c,"disputed"),self.local(self.b,"disputed"),"pending")
        self.assertEqual(self.store.read(),before)

    def test_no_mixed_route_and_no_auxiliary_traversal(self):
        a_root = self.local(self.a,"root")
        b_disputed = self.local(self.b,"disputed")
        self.assertNotIn(b_disputed,{n["id"] for n in neighbourhood(self.study(),a_root,10)["nodes"]})
        self.decide(self.local(self.a,"common"),self.local(self.b,"common"),"confirmed")
        result = neighbourhood(self.study(),a_root,10)
        self.assertNotIn(b_disputed,{n["id"] for n in result["nodes"]})
        self.assertEqual({e["accumulationSourceId"] for e in result["edges"]},{self.a["sid"]})
        together = neighbourhood(self.study(),self.local(self.a,"common"),1)
        self.assertEqual({e["accumulationSourceId"] for e in together["edges"]},{self.a["sid"],self.b["sid"]})
        zero = neighbourhood(self.study(),self.local(self.a,"common"),0)
        self.assertEqual((len(zero["nodes"]),len(zero["edges"])),(1,0))

    def test_source_filter_and_alias_do_not_mutate_source(self):
        original = copy.deepcopy(next(s for s in self.store.read()["state"]["studies"] if s["id"] == self.a["sid"]))
        self.act("accumulation_alias",studyId=self.sid,reference=reference(self.a["sid"],self.a["root"]),text="Новая запись")
        self.assertEqual(next(s for s in self.store.read()["state"]["studies"] if s["id"] == self.a["sid"]),original)
        self.assertFalse(lexical_index(self.study(),source_ids=[self.a["sid"]])["candidates"])
        self.assertEqual(len(lexical_index(self.study(),query="словар")["groups"]),1)

    def test_exchange_v3_preserves_decisions_and_detects_tampering(self):
        self.decide(self.local(self.a,"common"),self.local(self.b,"common"),"confirmed")
        self.decide(self.local(self.a,"disputed"),self.local(self.b,"disputed"),"rejected")
        document = graph_export(self.store,self.sid)
        self.assertEqual(document["version"],4)
        other = Store(Path(self.temp.name)/"import.sqlite3")
        added = other.mutate("import",{"document":document},other.read()["revision"])
        pending = [p["id"] for p in added["state"]["proposals"] if p["status"] == "pending"]
        other.mutate("review_proposals",{"proposalIds":pending,"decision":"accept"},other.read()["revision"])
        self.assertEqual(other.read()["state"]["studies"],[self.study()])
        again = other.mutate("import",{"document":document},other.read()["revision"])
        self.assertEqual(again["result"]["added"],0)
        self.assertEqual(Store(other.path).read()["state"]["studies"],[self.study()])
        bad = copy.deepcopy(document);bad["version"] = 2
        with self.assertRaisesRegex(Invalid,"v3"):
            parse_document(bad)
        bad = copy.deepcopy(document);bad.pop("history");bad["state"]["studies"][0]["edges"].pop()
        with self.assertRaises(Invalid):
            parse_document(bad)
        with self.assertRaisesRegex(Invalid,"целиком"):
            graph_export(self.store,self.sid,self.local(self.a,"common"),1)

    def test_source_drift_and_content_mutations_do_not_change_snapshot(self):
        before = copy.deepcopy(self.study())
        self.act("edit_node",studyId=self.a["sid"],nodeId=self.a["common"],label="изменено")
        self.assertEqual(self.study(),before)
        with self.assertRaises(Invalid):
            self.act("edit_node",studyId=self.sid,nodeId=self.local(self.a,"common"),label="подмена")
        with self.assertRaises(Invalid):
            self.act("accumulation_add_source",studyId=self.sid,sourceStudyId=self.a["sid"])
        with self.assertRaises(Invalid):
            self.act("create_accumulation",title="Вложенное",sourceStudyIds=[self.sid])

    def test_visual_and_neighbourhood_limits_report_incomplete_display(self):
        s = copy.deepcopy(self.study())
        # Grow immutable synthetic source before building its materialization.
        source = s["accumulation"]["sources"][0]
        root = source["snapshot"]["rootId"]
        for i in range(210):
            original = f"extra-{i}"
            source["snapshot"]["nodes"].append({"id":original,"label":"одинаковое","kind":"","notes":"","alternatives":"","source":"тест","origins":[]})
            source["nodeIds"][original] = f"copy-{i}"
            source["positions"][original] = {"x":i*10,"y":0}
            e = {"id":f"edge-{i}","from":root,"to":original,"type":"тест","notes":"","origins":[]}
            source["snapshot"]["edges"].append(e);source["edgeIds"][e["id"]] = f"edge-copy-{i}"
        from app.accumulation import projection
        s.update(projection(s["accumulation"],s))
        validate({"studies":[s],"matches":[],"imports":[],"proposals":[]})
        result = neighbourhood(s,self.local(self.a,"root"),1)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["nodes"]),150)
        self.assertGreater(result["totalNodes"],150)
        index = lexical_index(s,limit=1)
        self.assertTrue(index["candidatesTruncated"])
        self.assertLessEqual(len(index["candidates"]),1)


if __name__ == "__main__":
    unittest.main()
