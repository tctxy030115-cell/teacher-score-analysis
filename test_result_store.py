from copy import deepcopy
import unittest

from models import AnalysisResult, ResultKey
from services import ResultStore


class ResultStoreTest(unittest.TestCase):
    def make_key(self, signature_character="a"):
        return ResultKey(
            exam_id="exam-1",
            config_version=1,
            analysis_type="subject_analysis",
            request_signature=signature_character * 64,
        )

    def make_result(self, key, average=88.0):
        return AnalysisResult(
            key=key,
            payload={
                "average": average,
                "levels": {"excellent": ["student-1"]},
            },
        )

    def test_save_and_get_result(self):
        store = ResultStore()
        key = self.make_key()
        result = self.make_result(key)

        store.save(key, result)

        self.assertEqual(store.get(key), result)
        self.assertTrue(store.exists(key))

    def test_get_missing_key_returns_none(self):
        store = ResultStore()

        self.assertIsNone(store.get(self.make_key()))
        self.assertFalse(store.exists(self.make_key()))

    def test_different_keys_keep_results_isolated(self):
        store = ResultStore()
        first_key = self.make_key("a")
        second_key = self.make_key("b")
        first_result = self.make_result(first_key, average=88.0)
        second_result = self.make_result(second_key, average=92.0)

        store.save(first_key, first_result)
        store.save(second_key, second_result)

        self.assertEqual(store.get(first_key), first_result)
        self.assertEqual(store.get(second_key), second_result)

    def test_same_key_save_overwrites_previous_result(self):
        store = ResultStore()
        key = self.make_key()

        store.save(key, self.make_result(key, average=80.0))
        replacement = self.make_result(key, average=95.0)
        store.save(key, replacement)

        self.assertEqual(store.get(key), replacement)

    def test_clear_removes_all_results_from_current_store(self):
        store = ResultStore()
        first_key = self.make_key("a")
        second_key = self.make_key("b")
        store.save(first_key, self.make_result(first_key))
        store.save(second_key, self.make_result(second_key))

        store.clear()

        self.assertFalse(store.exists(first_key))
        self.assertFalse(store.exists(second_key))
        self.assertIsNone(store.get(first_key))

    def test_mutating_input_result_after_save_does_not_change_store(self):
        store = ResultStore()
        key = self.make_key()
        result = self.make_result(key)
        original_key = deepcopy(key)
        store.save(key, result)

        result.payload["average"] = 10.0
        result.payload["levels"]["excellent"].append("student-2")

        stored = store.get(key)
        self.assertEqual(stored.payload["average"], 88.0)
        self.assertEqual(
            stored.payload["levels"]["excellent"],
            ["student-1"],
        )
        self.assertEqual(key, original_key)

    def test_mutating_returned_result_does_not_change_store(self):
        store = ResultStore()
        key = self.make_key()
        store.save(key, self.make_result(key))

        returned = store.get(key)
        returned.payload["average"] = 20.0
        returned.payload["levels"]["excellent"].clear()

        stored_again = store.get(key)
        self.assertEqual(stored_again.payload["average"], 88.0)
        self.assertEqual(
            stored_again.payload["levels"]["excellent"],
            ["student-1"],
        )

    def test_store_instances_do_not_share_results(self):
        first_store = ResultStore()
        second_store = ResultStore()
        key = self.make_key()

        first_store.save(key, self.make_result(key))

        self.assertTrue(first_store.exists(key))
        self.assertFalse(second_store.exists(key))
        self.assertIsNone(second_store.get(key))


if __name__ == "__main__":
    unittest.main()
