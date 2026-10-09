import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.exchange import envelope, graph_export, neighbourhood, structural_diff
from app.server import make_server
from app.store import Conflict, Invalid, Store


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workspace.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def act(self, action, **data):
        return self.store.mutate(action, data, self.store.read()["revision"])["result"]

    def create(self, word):
        r = self.act("create_study", title=word)
        return r["studyId"], r["nodeId"]

    def get_study(self, sid):
        return next(s for s in self.store.read()["state"]["studies"] if s["id"] == sid)

    def get_node(self, sid, nid):
        return next(n for n in self.get_study(sid)["nodes"] if n["id"] == nid)

    def import_accept(self, document, allow=False):
        self.act("import", document=document)
        ids = [p["id"] for p in self.store.read()["state"]["proposals"] if p["status"] == "pending"]
        if ids:
            self.act("review_proposals", proposalIds=ids, decision="accept", allowConflicts=allow)

    def test_manual_scenario_cycles_merge_provenance_and_restart(self):
        a, ar = self.create("камень")
        b, br = self.create("камня")
        x = self.act("add_node", studyId=a, parentId=ar, label="твёрдый", kind="свойство", notes="Синтетическое пояснение A", relation="имеет свойство")["nodeId"]
        y = self.act("add_node", studyId=a, parentId=x, label="сопротивление деформации", kind="определение")["nodeId"]
        self.act("add_edge", studyId=a, **{"from": y, "to": ar, "type": "поясняется примером", "notes": "Цикл намеренный"})
        bx = self.act("add_node", studyId=b, parentId=br, label="твёрдый", kind="свойство", notes="Другое синтетическое пояснение B")["nodeId"]
        self.assertEqual(self.store.read()["state"]["matches"], [])
        self.assertEqual(neighbourhood(self.get_study(a), ar, None), {ar, x, y})
        accepted = self.act("match", leftStudy=a, leftNode=x, rightStudy=b, rightNode=bx, status="confirmed", reason="Тестовое ручное решение")["matchId"]
        rejected = self.act("match", leftStudy=a, leftNode=ar, rightStudy=b, rightNode=br, status="rejected", reason="Не отождествлять форму с формой")["matchId"]
        before_a = self.get_study(a)
        merged = self.act("merge", leftStudy=a, rightStudy=b, matchIds=[accepted], title="Тестовое объединение")
        output = self.get_study(merged["studyId"])
        self.assertEqual(len(output["nodes"]), 4)
        self.assertEqual(len(output["edges"]), 4)
        common = next(n for n in output["nodes"] if len(n["origins"]) == 2)
        self.assertIn("пояснение A", common["notes"])
        self.assertIn("пояснение B", common["notes"])
        self.assertEqual({o["nodeId"] for o in common["origins"]}, {x, bx})
        self.assertEqual(before_a, self.get_study(a))
        self.assertEqual(Store(self.path).read(), self.store.read())
        self.assertEqual(output["merge"]["decisions"][0]["reason"], "Тестовое ручное решение")
        with self.assertRaises(Invalid):
            self.act("merge", leftStudy=a, rightStudy=b, matchIds=[rejected], title="Недопустимо")

    def test_same_names_never_share_ids(self):
        a, ar = self.create("одно слово")
        b, br = self.create("одно слово")
        self.assertNotEqual(a, b)
        self.assertNotEqual(ar, br)
        self.assertEqual(self.store.read()["state"]["matches"], [])

    def test_snapshot_history_restore_and_stale_revision(self):
        a, ar = self.create("камень")
        rev = self.store.read()["revision"]
        self.act("edit_node", studyId=a, nodeId=ar, label="изменённое", kind="слово", notes="новое", alternatives="вариант", source="оператор")
        with self.assertRaises(Conflict):
            self.store.mutate("edit_study", {"studyId": a, "title": "потерянное"}, rev)
        self.act("restore", targetRevision=rev)
        self.assertEqual(self.get_node(a, ar)["label"], "камень")
        self.assertEqual(len(self.store.history()), 4)
        from app.journal import expand_history
        self.assertIn("новое", list(expand_history(self.store.export()))[2]["state"]["studies"][0]["nodes"][0]["notes"])

    def test_round_trip_study_ids_history_and_idempotence(self):
        a, ar = self.create("камень")
        self.act("add_node", studyId=a, parentId=ar, label="свойство")
        doc = graph_export(self.store, a)
        other = Store(Path(self.tmp.name) / "other.sqlite3")
        staged = other.mutate("import", {"document": doc}, 0)
        self.assertEqual(staged["state"]["studies"], [])
        ids = [p["id"] for p in staged["state"]["proposals"]]
        applied = other.mutate("review_proposals", {"proposalIds": ids, "decision": "accept"}, 1)
        self.assertEqual(applied["state"]["studies"][0], self.get_study(a))
        self.assertEqual(applied["state"]["imports"][0]["document"]["history"], doc["history"])
        repeated = other.mutate("import", {"document": doc}, 2)
        self.assertEqual(repeated["result"]["added"], 0)
        self.assertEqual(len(repeated["state"]["proposals"]), len(ids))

    def test_chatgpt_candidates_base_conflicts_rejection_and_atomicity(self):
        a, ar = self.create("камень")
        base = self.get_node(a, ar)
        value = {**base, "notes": "Предложение ChatGPT"}
        doc = envelope("changes", changes=[{"operation": "node", "studyId": a, "base": base, "value": value}])
        self.act("import", document=doc)
        self.assertEqual(self.get_node(a, ar), base)
        pid = self.store.read()["state"]["proposals"][0]["id"]
        self.act("edit_node", studyId=a, nodeId=ar, label="камень", notes="Ручное изменение", kind="слово")
        snapshot = self.store.read()
        with self.assertRaises(Invalid):
            self.act("review_proposals", proposalIds=[pid], decision="accept")
        self.assertEqual(snapshot, self.store.read())
        self.act("review_proposals", proposalIds=[pid], decision="accept", allowConflicts=True)
        self.assertEqual(self.get_node(a, ar), value)
        addition = envelope("changes", changes=[{"operation": "node", "studyId": a, "base": None, "value": {"id": "candidate-id", "label": "Не принято", "kind": "", "notes": "", "alternatives": "", "source": "", "origins": []}}])
        self.act("import", document=addition)
        pid = self.store.read()["state"]["proposals"][-1]["id"]
        self.act("review_proposals", proposalIds=[pid], decision="reject")
        self.assertNotIn("candidate-id", [n["id"] for n in self.get_study(a)["nodes"]])

    def test_invalid_dependent_patch_rolls_back_everything(self):
        a, ar = self.create("камень")
        changes = envelope("changes", changes=[{"operation": "node", "studyId": a, "base": None, "value": {"id": "new", "label": "Новое"}}, {"operation": "edge", "studyId": a, "base": None, "value": {"id": "edge", "from": ar, "to": "missing", "type": "ошибка"}}])
        self.act("import", document=changes)
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.act("review_proposals", proposalIds=[p["id"] for p in before["state"]["proposals"]], decision="accept")
        self.assertEqual(self.store.read(), before)

    def test_unrelated_ids_and_broken_import_rejected(self):
        a, ar = self.create("камень")
        b, br = self.create("камня")
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.act("add_edge", studyId=a, **{"from": ar, "to": br, "type": "нет"})
        self.assertEqual(self.store.read(), before)
        doc = self.store.export()
        doc["state"]["studies"][1]["nodes"][0]["id"] = ar
        with self.assertRaises(Invalid):
            self.act("import", document=doc)
        doc["version"] = 999
        with self.assertRaises(Invalid):
            self.act("import", document=doc)

    def test_fragment_depth_cycle_and_import_into_source(self):
        a, ar = self.create("камень")
        x = self.act("add_node", studyId=a, parentId=ar, label="второй")["nodeId"]
        y = self.act("add_node", studyId=a, parentId=x, label="третий")["nodeId"]
        s = self.get_study(a)
        self.assertEqual(neighbourhood(s, ar, 0), {ar})
        self.assertEqual(neighbourhood(s, ar, 1), {ar, x})
        self.assertEqual(neighbourhood(s, ar, 2), {ar, x, y})
        doc = graph_export(self.store, a, x, 0)
        self.assertEqual([n["id"] for n in doc["state"]["studies"][0]["nodes"]], [x])
        result = self.act("import", document=doc)
        self.assertEqual(result["added"], 0)
        self.assertEqual(self.get_study(a)["rootId"], ar)

    def test_diff_independent_and_versions_never_infer_identity(self):
        a, ar = self.create("камень")
        b, br = self.create("камень")
        left = self.get_study(a)
        diff = structural_diff(left, self.get_study(b))
        self.assertEqual(diff["aligned"], [])
        self.assertEqual(diff["onlyLeft"], [ar])
        self.act("match", leftStudy=a, leftNode=ar, rightStudy=b, rightNode=br, status="confirmed", reason="Тест")
        diff = structural_diff(left, self.get_study(b), self.store.read()["state"]["matches"])
        self.assertEqual(len(diff["aligned"]), 1)
        self.act("edit_node", studyId=a, nodeId=ar, label="камень", kind="слово", notes="новая версия")
        self.assertEqual(self.store.read()["state"]["matches"][0]["status"], "pending")
        versions = structural_diff(left, self.get_study(a))
        self.assertEqual(versions["aligned"][0]["differences"]["notes"]["right"], "новая версия")

    def test_root_deletion_is_blocked_archive_reversible(self):
        a, ar = self.create("камень")
        with self.assertRaises(Invalid):
            self.act("delete_node", studyId=a, nodeId=ar)
        self.act("archive_study", studyId=a, archived=True)
        self.assertTrue(self.get_study(a)["archived"])
        self.act("archive_study", studyId=a, archived=False)
        self.assertFalse(self.get_study(a)["archived"])

    def test_new_candidate_nodes_edges_and_repeated_pending_import(self):
        a, ar = self.create("камень")
        doc = envelope("changes", changes=[{"operation": "node", "studyId": a, "base": None, "value": {"id": "new-node", "label": "Предложено", "customAttribute": {"confidence": "не оценивалась"}}}, {"operation": "edge", "studyId": a, "base": None, "value": {"id": "new-edge", "from": ar, "to": "new-node", "type": "произвольное отношение"}}])
        self.act("import", document=doc)
        repeated = self.act("import", document=doc)
        self.assertEqual(repeated["added"], 0)
        self.assertEqual(len(self.store.read()["state"]["proposals"]), 2)
        self.import_accept(doc)
        self.assertEqual(self.get_node(a, "new-node")["customAttribute"]["confidence"], "не оценивалась")
        self.assertEqual(self.get_study(a)["edges"][0]["to"], "new-node")

    def test_simultaneous_conflicting_proposals_cannot_silently_overwrite(self):
        a, ar = self.create("камень")
        base = self.get_node(a, ar)
        for text in ("первая версия", "вторая версия"):
            self.act("import", document=envelope("changes", changes=[{"operation": "node", "studyId": a, "base": base, "value": {**base, "notes": text}}]))
        before = self.store.read()
        with self.assertRaises(Invalid):
            self.act("review_proposals", proposalIds=[p["id"] for p in before["state"]["proposals"]], decision="accept", allowConflicts=True)
        self.assertEqual(self.store.read(), before)

    def test_id_collision_is_detected_before_acceptance(self):
        from app.exchange import conflict
        a, ar = self.create("камень")
        b, br = self.create("камня")
        doc = envelope("changes", changes=[{"operation": "node", "studyId": a, "base": None, "value": {**self.get_node(b, br), "notes": "Коллизия"}}])
        staged = self.act("import", document=doc)
        self.assertEqual(staged["conflicts"], 1)
        p = self.store.read()["state"]["proposals"][0]
        self.assertTrue(conflict(self.store.read()["state"], p))
        with self.assertRaisesRegex(Invalid, "Конфликт ID"):
            self.act("review_proposals", proposalIds=[p["id"]], decision="accept", allowConflicts=True)

    def test_structure_edit_invalidates_old_semantic_decisions(self):
        a, ar = self.create("камень")
        b, br = self.create("камня")
        self.act("match", leftStudy=a, leftNode=ar, rightStudy=b, rightNode=br, status="confirmed", reason="До изменения")
        self.act("add_node", studyId=a, parentId=ar, label="Новая характеристика")
        self.assertEqual(self.store.read()["state"]["matches"][0]["status"], "pending")
        self.assertIn("До изменения", self.store.read()["state"]["matches"][0]["reason"])

    def test_many_to_many_diff_and_transitive_merge(self):
        a, ar = self.create("камень")
        b, br = self.create("камня")
        extra = self.act("add_node", studyId=b, label="альтернатива")["nodeId"]
        ids = [self.act("match", leftStudy=a, leftNode=ar, rightStudy=b, rightNode=n, status="confirmed", reason="Синтетическое транзитивное решение")["matchId"] for n in (br, extra)]
        diff = structural_diff(self.get_study(a), self.get_study(b), self.store.read()["state"]["matches"])
        self.assertEqual(len(diff["aligned"]), 2)
        self.assertEqual(diff["onlyRight"], [])
        merged = self.act("merge", leftStudy=a, rightStudy=b, title="Транзитивное объединение", matchIds=ids)
        nodes = self.get_study(merged["studyId"])["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(len(nodes[0]["origins"]), 3)

    def test_version_diff_contains_attributes_and_reviewable_changes(self):
        a, ar = self.create("камень")
        left = self.get_study(a)
        self.act("position", studyId=a, nodeId=ar, x=100, y=50)
        self.act("add_node", studyId=a, parentId=ar, label="Новый в версии")
        right = self.get_study(a)
        diff = structural_diff(left, right)
        self.assertIn("x", diff["aligned"][0]["differences"])
        self.assertEqual(len(diff["versionChanges"]["changes"]), 3)
        self.act("restore", targetRevision=1)
        self.import_accept(diff["versionChanges"])
        self.assertEqual(self.get_study(a), right)

    def test_fragment_does_not_leak_unrelated_imported_graph(self):
        from scripts.fixtures import small
        self.import_accept(small())
        a = self.store.read()["state"]["studies"][0]
        fragment = graph_export(self.store, a["id"], a["rootId"], 0)
        self.assertEqual(len(fragment["state"]["studies"]), 1)
        self.assertEqual(len(fragment["state"]["studies"][0]["nodes"]), 1)
        for imp in fragment["state"]["imports"]:
            self.assertEqual(len(imp["document"]["state"]["studies"]), 1)
            self.assertEqual(len(imp["document"]["state"]["studies"][0]["nodes"]), 1)

    def test_accepted_patch_cannot_erase_merge_origins(self):
        a, ar = self.create("камень")
        b, br = self.create("камня")
        mid = self.act("match", leftStudy=a, leftNode=ar, rightStudy=b, rightNode=br, status="confirmed")["matchId"]
        result = self.act("merge", leftStudy=a, rightStudy=b, matchIds=[mid], title="Происхождение")
        merged = self.get_study(result["studyId"])
        base = merged["nodes"][0]
        self.import_accept(envelope("changes", changes=[{"operation": "node", "studyId": merged["id"], "base": base, "value": {**base, "origins": [], "notes": "Предлагаемая правка"}}]))
        changed = self.get_node(merged["id"], base["id"])
        self.assertEqual(changed["origins"], base["origins"])
        self.assertEqual(changed["notes"], "Предлагаемая правка")

    def test_http_security_persistence_and_errors(self):
        server = make_server(self.path, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(url + "/api/state") as response:
                initial = json.load(response)
            payload = json.dumps({"action": "create_study", "revision": 0, "data": {"title": "камень"}}).encode()
            request = Request(url + "/api/action", data=payload, headers={"Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as err:
                urlopen(request)
            self.assertEqual(err.exception.code, 403)
            request.add_header("X-Workspace-Token", initial["token"])
            request.add_header("Origin", "https://foreign.example")
            with self.assertRaises(HTTPError) as err:
                urlopen(request)
            self.assertEqual(err.exception.code, 403)
            request.remove_header("Origin")
            with urlopen(request) as response:
                result = json.load(response)
            self.assertEqual(result["state"]["studies"][0]["title"], "камень")
            with self.assertRaises(HTTPError) as err:
                urlopen(request)
            self.assertEqual(err.exception.code, 409)
            bad_host = Request(url + "/api/state", headers={"Host": "foreign.example"})
            with self.assertRaises(HTTPError) as err:
                urlopen(bad_host)
            self.assertEqual(err.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        restarted = make_server(self.path, 0)
        self.assertEqual(Store(self.path).read()["state"]["studies"][0]["title"], "камень")
        restarted.server_close()


if __name__ == "__main__":
    unittest.main()
