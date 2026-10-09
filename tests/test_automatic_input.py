from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import automatic_input as ai


class AutomaticInputChecks(unittest.TestCase):
    def test_parser_receives_only_surface_forms(self):
        try:
            import ufal.udpipe
        except ImportError:
            self.skipTest("Optional parser dependency; run with .venv/Scripts/python.exe")
        tokens = [dict(id=1, form="Он", lemma="secret", pos="SECRET", head=999, rel="secret", deps="1:nsubj")]
        sent = ai.blank_sentence(tokens)
        self.assertEqual(sent.words[1].form, "Он")
        self.assertNotEqual(sent.words[1].lemma, "secret")
        self.assertNotEqual(sent.words[1].upostag, "SECRET")
        self.assertNotEqual(sent.words[1].head, 999)
        self.assertNotEqual(sent.words[1].deprel, "secret")
        self.assertNotEqual(sent.words[1].deps, "1:nsubj")


if __name__ == "__main__":
    unittest.main()
