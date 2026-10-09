import copy
import tempfile
import unittest
from pathlib import Path

from app.composition import edge_role, replacement_preview
from app.exchange import graph_export, structural_diff
from app.journal import expand_history
from app.store import Invalid, Store, decode, validate


class CompositionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "workspace.sqlite3")
        root = self.act("create_study", title="X")
        self.sid, self.x = root["studyId"], root["nodeId"]

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, **data):
        return self.store.mutate(action, data, self.store.read()["revision"])["result"]

    def study(self):
        return next(s for s in self.store.read()["state"]["studies"] if s["id"] == self.sid)

    def add(self, label="", combination=False, **values):
        return self.act("add_node", studyId=self.sid, label=label, structure="combination" if combination else "concept", **values)["nodeId"]

    def edge(self, a, b, component=False, **values):
        self.act("add_edge", studyId=self.sid, **{"from": a, "to": b, "role": "component" if component else "relation", **values})
        return self.study()["edges"][-1]

    def alpha(self):
        hardness = self.add("твёрдость")
        modifier = self.add("носитель свойства")
        alpha = self.add(combination=True)
        self.edge(alpha, hardness, True, componentRole="основа")
        self.edge(alpha, modifier, True, componentRole="модификатор")
        return alpha, hardness, modifier

    def import_accept(self, other, document):
        staged = other.mutate("import", {"document": document}, other.read()["revision"])
        selected = [p["id"] for p in staged["state"]["proposals"] if p["status"] == "pending"]
        if selected:
            other.mutate("review_proposals", {"decision": "accept", "proposalIds": selected}, other.read()["revision"])

    def test_anonymous_identity_membership_and_no_assertion_propagation(self):
        alpha, hardness, _ = self.alpha()
        beta = self.add(combination=True)
        self.edge(beta, alpha, True)
        self.edge(self.x, beta, type="имеет свойство")
        graph = self.study()
        self.assertNotEqual(alpha, beta)
        self.assertTrue(all(n["label"] == "" and n["kind"] == "" for n in graph["nodes"] if n["id"] in (alpha, beta)))
        assertions = [(e["from"], e["to"], e["type"]) for e in graph["edges"] if edge_role(e) == "relation"]
        self.assertEqual(assertions, [(self.x, beta, "имеет свойство")])
        self.assertNotIn((self.x, hardness, "имеет свойство"), assertions)
        self.edge(alpha, beta, True)  # Membership cycles remain representable, not inferred.
        validate(self.store.read()["state"])

    def test_shared_component_does_not_identify_assertions(self):
        prop = self.add("свойство")
        left, right = self.add(combination=True), self.add(combination=True)
        self.edge(left, prop, True)
        self.edge(right, prop, True)
        self.edge(self.x, left, type="утверждение A")
        source = self.add("Y")
        self.edge(source, right, type="утверждение B")
        graph = self.study()
        self.assertEqual(len(graph["nodes"]), 5)
        self.assertEqual(len(graph["edges"]), 4)
        self.assertEqual(self.store.read()["state"]["matches"], [])
        self.assertFalse(any(e["from"] == self.x and e["to"] in (prop, right) for e in graph["edges"]))

    def test_substitution_preserves_incoming_outgoing_membership_and_lexicon(self):
        alpha, _, _ = self.alpha()
        word = self.add("твёрдый", notes="Исходное содержательное пояснение", alternatives="Другой смысл", source="Ручное исследование")
        beta = self.add(combination=True)
        incoming = self.edge(self.x, word, type="характеризуется", notes="Контекст X")
        outgoing = self.edge(word, self.x, type="объясняет", notes="Контекст слова")
        member = self.edge(beta, word, True, componentRole="роль")
        designation = self.act("add_designation", studyId=self.sid, text="твердое", target=word)
        before = self.study()
        result = self.act("replace_concept", studyId=self.sid, sourceId=word, targetId=alpha, confirmed=True, reason="Синтетическое подтверждение оператора")
        graph = self.study()
        self.assertNotIn(word, [n["id"] for n in graph["nodes"]])
        self.assertTrue(any(d["text"] == "твёрдый" and d["target"] == alpha for d in graph["designations"]))
        self.assertEqual(next(d for d in graph["designations"] if d["id"] == designation["designationId"])["target"], alpha)
        for original in (incoming, outgoing, member):
            remapped = next(e for e in graph["edges"] if e["id"] == original["id"])
            self.assertEqual(remapped, {**original, "from": alpha if original["from"] == word else original["from"], "to": alpha if original["to"] == word else original["to"]})
        record = graph["substitutions"][0]
        self.assertEqual(record["before"]["source"], next(n for n in before["nodes"] if n["id"] == word))
        self.act("restore_substitution", studyId=self.sid, substitutionId=result["substitutionId"])
        restored = self.study()
        for key in ("nodes", "edges", "rootId", "designations"):
            self.assertEqual(restored[key], before[key])
        self.assertEqual(restored["substitutions"][0]["status"], "restored")

    def test_root_substitution_and_match_retarget_require_new_review(self):
        alpha, _, _ = self.alpha()
        other = self.act("create_study", title="Независимое")
        self.act("match", leftStudy=self.sid, leftNode=self.x, rightStudy=other["studyId"], rightNode=other["nodeId"], status="confirmed", reason="До замещения")
        self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Синтетическое решение")
        state = self.store.read()["state"]
        self.assertEqual(self.study()["rootId"], alpha)
        self.assertEqual(state["matches"][0]["leftNode"], alpha)
        self.assertEqual(state["matches"][0]["status"], "pending")
        self.assertEqual(next(s for s in state["studies"] if s["id"] == other["studyId"])["nodes"][0]["id"], other["nodeId"])

    def test_ambiguous_replacement_and_unconfirmed_operation_are_atomic(self):
        alpha, _, _ = self.alpha()
        self.edge(alpha, self.x, True)
        before = self.store.read()
        preview = replacement_preview(before["state"], self.sid, self.x, alpha)
        self.assertFalse(preview["canReplace"])
        with self.assertRaisesRegex(Invalid, "самоопределение"):
            self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Нельзя")
        self.assertEqual(before, self.store.read())
        empty = self.add(combination=True)
        with self.assertRaisesRegex(Invalid, "нет компонентов"):
            self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=empty, confirmed=True, reason="Нельзя")
        safe, _, _ = self.alpha()
        with self.assertRaisesRegex(Invalid, "Подтвердите"):
            self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=safe, reason="Тест")

    def test_ambiguous_match_collision_and_self_link_block_replacement(self):
        alpha, _, _ = self.alpha()
        other = self.act("create_study", title="Другое")
        for identity in (self.x, alpha):
            self.act("match", leftStudy=self.sid, leftNode=identity, rightStudy=other["studyId"], rightNode=other["nodeId"], status="pending")
        self.assertFalse(replacement_preview(self.store.read()["state"], self.sid, self.x, alpha)["canReplace"])
        word = self.add("твёрдый")
        self.edge(word, alpha, type="выражается через")
        self.assertFalse(replacement_preview(self.store.read()["state"], self.sid, word, alpha)["canReplace"])

    def test_undo_refuses_changed_context_and_history_restores_original(self):
        alpha, _, _ = self.alpha()
        baseline = self.store.read()
        result = self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Тест")
        self.edge(alpha, self.add("Новый компонент"), True)
        changed = self.store.read()
        with self.assertRaisesRegex(Invalid, "контекст изменился"):
            self.act("restore_substitution", studyId=self.sid, substitutionId=result["substitutionId"])
        self.assertEqual(changed, self.store.read())
        self.act("restore", targetRevision=baseline["revision"])
        self.assertEqual(self.store.read()["state"], baseline["state"])

    def test_v1_database_and_export_are_preserved_and_v2_roundtrip(self):
        fixture = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "manual-example.json"
        import json
        legacy = json.loads(fixture.read_text(encoding="utf-8"))
        original = copy.deepcopy(legacy)
        self.import_accept(self.store, legacy)
        self.assertEqual(legacy, original)
        self.assertEqual(self.store.read()["state"]["studies"][-2:], legacy["state"]["studies"])
        with self.store.connect() as db:
            raw_before = db.execute("SELECT state FROM revisions WHERE id=1").fetchone()[0]
        Store(self.store.path).read()
        with self.store.connect() as db:
            raw_after = db.execute("SELECT state FROM revisions WHERE id=1").fetchone()[0]
        self.assertEqual(raw_before, raw_after)
        alpha, _, _ = self.alpha()
        self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Тест")
        document = graph_export(self.store, self.sid)
        self.assertEqual(document["version"], 2)
        self.assertEqual(list(expand_history(document))[-1]["state"], document["state"])
        other = Store(Path(self.temp.name) / "other.sqlite3")
        self.import_accept(other, document)
        self.assertEqual(other.read()["state"]["studies"][0], self.study())
        duplicate = other.mutate("import", {"document": document}, other.read()["revision"])
        self.assertEqual(duplicate["result"]["added"], 0)
        fragment = graph_export(self.store, self.sid, alpha, 0)
        validate(fragment["state"])
        self.assertEqual(len(fragment["state"]["studies"][0]["designations"]), 1)
        self.assertEqual(len(fragment["state"]["studies"][0]["substitutions"]), 1)

    def test_composition_merge_keeps_dictionary_and_substitution_evidence(self):
        alpha, _, _ = self.alpha()
        self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Тест")
        original = self.study()
        second = self.act("create_study", title="Независимая структура")
        match = self.act("match", leftStudy=self.sid, leftNode=alpha, rightStudy=second["studyId"], rightNode=second["nodeId"], status="confirmed", reason="Только проверка механики")
        merged = self.act("merge", leftStudy=self.sid, rightStudy=second["studyId"], matchIds=[match["matchId"]], title="Объединение")
        result = next(s for s in self.store.read()["state"]["studies"] if s["id"] == merged["studyId"])
        validate(self.store.read()["state"])
        self.assertEqual(result["designations"][0]["text"], "X")
        self.assertEqual(result["substitutions"][0]["status"], "archived")
        self.assertEqual(result["substitutions"][0]["before"], original["substitutions"][0]["before"])
        self.assertEqual(result["substitutions"][0]["sourceTargetId"], alpha)
        self.assertEqual(result["substitutions"][0]["targetId"], merged["nodeId"])
        self.assertTrue(any(e["role"] == "component" and e["from"] == merged["nodeId"] for e in result["edges"]))

    def test_diff_preserves_removed_substitution_as_explicit_candidate(self):
        alpha, _, _ = self.alpha()
        before = self.study()
        self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Тест")
        after = self.study()
        changes = structural_diff(after, before)["versionChanges"]["changes"]
        self.assertTrue(any(c["operation"] == "delete_substitution" and c["base"] == after["substitutions"][0] for c in changes))
        result = self.act("import", document=structural_diff(after, before)["versionChanges"])
        self.assertGreater(result["added"], 0)
        candidates = [p["id"] for p in self.store.read()["state"]["proposals"] if p["status"] == "pending"]
        self.act("review_proposals", proposalIds=candidates, decision="accept")
        restored = self.study()
        self.assertEqual(restored["substitutions"], [])
        self.assertEqual(restored["rootId"], before["rootId"])
        self.assertEqual(restored["edges"], before["edges"])
        self.assertEqual({n["id"] for n in restored["nodes"]}, {n["id"] for n in before["nodes"]})
        # Imported reverse patches preserve provenance already acquired by alpha.
        self.assertTrue(next(n for n in restored["nodes"] if n["id"] == alpha)["origins"])

    def test_malformed_substitution_context_is_rejected_without_write(self):
        alpha, _, _ = self.alpha()
        self.act("replace_concept", studyId=self.sid, sourceId=self.x, targetId=alpha, confirmed=True, reason="Тест")
        saved = self.store.read()
        malformed = copy.deepcopy(saved["state"])
        malformed["studies"][0]["substitutions"][0]["before"].pop("source")
        with self.assertRaises(Invalid):
            validate(malformed)
        self.assertEqual(self.store.read(), saved)

    def test_reproducible_composition_fixtures_and_large_membership(self):
        import json
        from scripts.fixtures import compositions, large_composition
        fixture = Path(__file__).resolve().parents[1] / "data/fixtures/composition-example.json"
        self.assertEqual(json.loads(fixture.read_text(encoding="utf-8")), compositions())
        self.import_accept(self.store, compositions())
        self.import_accept(self.store, large_composition())
        state = self.store.read()["state"]
        validate(state)
        large = next(s for s in state["studies"] if len(s["nodes"]) == 2001)
        self.assertEqual(len(large["edges"]), 2000)
        self.assertTrue(all(e["role"] == "component" and e["from"] == large["rootId"] for e in large["edges"]))
        self.assertEqual(len(graph_export(self.store, large["id"], large["rootId"], 1)["state"]["studies"][0]["nodes"]), 2001)

    def test_component_role_is_not_relation_in_structural_diff(self):
        alpha, _, _ = self.alpha()
        left = self.study()
        right = copy.deepcopy(left)
        right["id"] = "other-study"
        for n in right["nodes"]:
            n["id"] = "other/" + n["id"]
        right["rootId"] = "other/" + right["rootId"]
        for e in right["edges"]:
            e.update(id="other/" + e["id"], **{"from": "other/" + e["from"], "to": "other/" + e["to"], "role": "relation"})
        matches = [{"id": "match/"+n["id"], "leftStudy": left["id"], "leftNode": n["id"], "rightStudy": right["id"], "rightNode": "other/"+n["id"], "status": "confirmed"} for n in left["nodes"]]
        self.assertEqual(structural_diff(left, right, matches)["relationAlignments"], [])


if __name__ == "__main__":
    unittest.main()
