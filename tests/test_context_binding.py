import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("context_binding", ROOT / "scripts/context_binding.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)


class BindingChecks(unittest.TestCase):
    @staticmethod
    def episode():
        # A tries to begin to read B; supplied labels are solely training observation.
        return [dict(id=1, lemma="a", pos="NOUN", head=2, rel="nsubj", deps="2:nsubj|3:nsubj:xsubj|4:nsubj:xsubj"),
                dict(id=2, lemma="try", pos="VERB", head=0, rel="root", deps="0:root"),
                dict(id=3, lemma="begin", pos="VERB", head=2, rel="xcomp", deps="2:xcomp"),
                dict(id=4, lemma="read", pos="VERB", head=3, rel="xcomp", deps="3:xcomp"),
                dict(id=5, lemma="b", pos="NOUN", head=4, rel="obj", deps="4:obj")]

    def test_learn_execute_and_remove_proof(self):
        ops = cb.Operators()
        tokens = self.episode()
        ops.observe({"sent_id": "train.xml_1", "text": "x"}, tokens)
        nodes, children = cb.graph(tokens)
        self.assertTrue(all("deps" not in n for n in nodes.values()))
        self.assertEqual(ops.bind(4, nodes, children, "learned_recursive")[0], {1})
        self.assertEqual(ops.bind(4, nodes, children, "learned_local")[0], set())
        tokens[0]["head"] = 0
        nodes, children = cb.graph(tokens)
        self.assertEqual(ops.bind(4, nodes, children, "learned_recursive")[0], set())

    def test_ids_and_token_order_are_not_semantic(self):
        ops = cb.Operators()
        tokens = self.episode()
        ops.observe({"sent_id": "train.xml_1"}, tokens)
        mapping = {0: 0, 1: 83, 2: 7, 3: 92, 4: 31, 5: 12}
        remapped = [{**t, "id": mapping[t["id"]], "head": mapping[t["head"]]} for t in reversed(tokens)]
        nodes, children = cb.graph(remapped)
        self.assertEqual(ops.bind(31, nodes, children, "learned_recursive")[0], {83})

    def test_object_control_is_learned_and_generalizes(self):
        ops = cb.Operators()
        tokens = self.episode()[:3]
        tokens[1]["lemma"] = "force"
        tokens[0]["deps"] = "2:nsubj"
        tokens.append(dict(id=6, lemma="c", pos="NOUN", head=2, rel="obj", deps="2:obj|3:nsubj:xsubj"))
        ops.observe({"sent_id": "train.xml_1"}, tokens)
        tokens[2]["lemma"] = "new_action"
        nodes, children = cb.graph(tokens)
        self.assertEqual(ops.bind(3, nodes, children, "learned_recursive")[0], {6})
        self.assertEqual(ops.bind(3, nodes, children, "pair_memory")[0], set())
        self.assertEqual(ops.bind(3, nodes, children, "subject_rule")[0], {1})


if __name__ == "__main__":
    unittest.main()
