from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import conditional_operators as co
import context_binding as cb


class ConditionalChecks(unittest.TestCase):
    def test_signature_contains_only_basic_structure(self):
        tokens = [dict(id=1, lemma="x", pos="NOUN", head=2, rel="nsubj", deps="99:nsubj"),
                  dict(id=2, lemma="v", pos="VERB", head=0, rel="root", deps="99:obj")]
        nodes, children = cb.graph(tokens)
        self.assertEqual(co.signature(nodes[2], children), "10000")
        tokens[0]["deps"] = "2:obj|3:nsubj"
        nodes2, children2 = cb.graph(tokens)
        self.assertEqual(co.signature(nodes2[2], children2), "10000")

    def test_learned_context_survives_predicate_renaming(self):
        ops = co.ConditionalOperators()
        for i, lemma in enumerate(("give", "allow", "recommend")):
            tokens = [dict(id=1, lemma="a", pos="NOUN", head=2, rel="nsubj", deps="2:nsubj"),
                      dict(id=2, lemma=lemma, pos="VERB", head=0, rel="root", deps="0:root"),
                      dict(id=3, lemma="b", pos="NOUN", head=2, rel="iobj", deps="2:iobj|4:nsubj"),
                      dict(id=4, lemma="action", pos="VERB", head=2, rel="xcomp", deps="2:xcomp")]
            ops.observe({"sent_id": f"doc{i}.xml_1"}, tokens)
        tokens[1]["lemma"] = "unknown"
        nodes, children = cb.graph(tokens)
        self.assertEqual(ops.bind(4, nodes, children, "context_global")[0], {3})
        self.assertEqual(ops.bind(4, nodes, children, "context_lexical")[0], {3})

    def test_fold_assignment_stable(self):
        docs = [f"doc{i}.xml" for i in range(100)]
        self.assertEqual({co.fold_of(d) for d in docs}, set(range(5)))
        self.assertEqual([co.fold_of(d) for d in docs], list(reversed([co.fold_of(d) for d in reversed(docs)])))


if __name__ == "__main__":
    unittest.main()
