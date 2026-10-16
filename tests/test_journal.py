import copy
import unittest

from app.journal import apply_patch, compact_history, expand_history, patch_between
from app.store import Invalid


class JournalTest(unittest.TestCase):
    def test_lists_with_stable_ids_insert_remove_update(self):
        before = {"items": [{"id": "a", "value": 1}, {"id": "b", "value": 2}, {"id": "c", "value": 3}]}
        for items in ([{"id": "x", "value": 0}, {"id": "a", "value": 4}, {"id": "c", "value": 3}], [{"id": "c", "value": 3}, {"id": "a", "value": 1}], [], [{"id": "a", "value": 1}, {"id": "b", "value": 5}, {"id": "c", "value": 3}, {"id": "d", "value": 6}]):
            after = {"items": items}
            self.assertEqual(apply_patch(before, patch_between(before, after)), after)
        self.assertEqual(before["items"][0]["value"], 1)

    def test_json_pointer_escaping_and_scalar_changes(self):
        before = {"a/b": {"x~y": [1, 2]}, "remove": False}
        after = {"a/b": {"x~y": [2, 4]}, "addition": "новое"}
        patch = patch_between(before, after)
        self.assertTrue(any("a~1b/x~0y" in p["path"] for p in patch))
        self.assertEqual(apply_patch(before, patch), after)

    def test_corrupt_paths_operations_and_missing_values_rejected(self):
        for patch in ([{"op": "remove", "path": "/missing"}], [{"op": "replace", "path": "/items/-1", "value": 0}], [{"op": "unknown", "path": ""}], [{"op": "add", "path": "wrong", "value": 1}], [{"op": "add", "path": "/field"}], [{"op": "replace", "path": "/items/10", "value": 1}]):
            with self.assertRaises(Invalid):
                apply_patch({"items": [1]}, patch)




if __name__ == "__main__":
    unittest.main()
