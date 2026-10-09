"""Checks for leakage, role direction, active filtering and data provenance."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("role_transfer", ROOT / "scripts/role_transfer.py")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


class ExperimentChecks(unittest.TestCase):
    def test_no_position_shortcut_and_unknown_tie(self):
        memory = rt.Memory([("читать", "ученик", 0), ("читать", "книга", 1)])
        base = {"id": "x", "doc": "d", "v": "читать", "s": "ученик", "o": "книга"}
        self.assertEqual(memory.evaluate([base], "pair_memory")[0]["correct"], 1)
        swapped = {**base, "s": "книга", "o": "ученик"}
        self.assertEqual(memory.evaluate([swapped], "pair_memory")[0]["correct"], 0)
        unknown = {**base, "s": "a", "o": "b"}
        self.assertEqual(memory.evaluate([unknown], "pair_memory")[0]["correct"], 0.5)

    def test_novelty_and_no_test_learning(self):
        memory = rt.Memory([("читать", "ученик", 0), ("читать", "книга", 1)])
        t = {"v": "читать", "s": "ученик", "o": "газета", "id": "x", "doc": "d"}
        self.assertEqual(rt.categorize([t], memory, [])[0]["bucket"], "one_pair_new")
        before = dict(memory.pair)
        memory.evaluate([t], "transfer")
        self.assertEqual(dict(memory.pair), before)
        self.assertNotIn("газета", memory.noun)

    def test_extraction_filters(self):
        def tok(i, lemma, pos, head, rel, feats="_"):
            return dict(id=i, lemma=lemma, pos=pos, head=head, rel=rel, feats=feats)
        ts = [tok(1, "ученик", "NOUN", 2, "nsubj"), tok(2, "читать", "VERB", 0, "root"), tok(3, "книга", "NOUN", 2, "obj")]
        arcs, triples = rt.observations({"sent_id": "doc.xml_1"}, ts)
        self.assertEqual(arcs, [("читать", "ученик", 0), ("читать", "книга", 1)])
        self.assertEqual(triples[0]["doc"], "doc.xml")
        self.assertEqual(rt.observations({}, ts + [tok(4, "не", "PART", 2, "advmod")]), ([], []))
        ts[1]["feats"] = "Voice=Pass"
        self.assertEqual(rt.observations({}, ts), ([], []))

    def test_source_hashes(self):
        import hashlib
        manifest = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))
        for source in manifest:
            self.assertEqual(hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest(), source["sha256"])


if __name__ == "__main__":
    unittest.main()
