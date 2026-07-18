from copy import deepcopy
import unittest

from models import AnalysisRequest
from services import ResultStore, adapt_analysis_result, build_result_key
from services.report_result_service import (
    analysis_result_to_legacy_dict,
    get_or_build_report_result,
)


class ReportResultServiceTest(unittest.TestCase):
    def make_request(self, exam_id="exam-1"):
        return AnalysisRequest(
            exam_id=exam_id,
            page_name="report_center",
            analysis_type="report_center",
            subject="数学",
            selected_classes=("2401",),
            config_version=2,
            config_signature="a" * 64,
            state_signature="b" * 64,
        )

    def make_legacy_result(self, average=91.5):
        return {
            "current_class": "2401",
            "current_subject": "数学",
            "student_count": 2,
            "average_score": average,
            "highest_score": 98.0,
            "lowest_score": 85.0,
            "excellent_count": 1,
            "good_count": 1,
            "pass_count": 2,
            "fail_count": 0,
            "excellent_rate": 50.0,
            "pass_rate": 100.0,
            "full_score": 120.0,
            "excellent_percent": 90.0,
            "good_percent": 80.0,
            "pass_percent": 60.0,
            "score_details": [["张三", 98.0, "优秀"]],
            "excellent_students": [["张三", 98.0]],
            "fail_students": [],
        }

    def test_existing_store_result_is_returned(self):
        store = ResultStore()
        request = self.make_request()
        legacy = self.make_legacy_result()

        expected_key = build_result_key(request)
        cached = adapt_analysis_result(expected_key, legacy)
        store.save(expected_key, cached)

        result = get_or_build_report_result(request, store, {"average_score": 0})

        self.assertEqual(result, cached)

    def test_store_miss_adapts_legacy_result(self):
        store = ResultStore()
        legacy = self.make_legacy_result()

        result = get_or_build_report_result(self.make_request(), store, legacy)

        self.assertIsNotNone(result)
        self.assertEqual(result.payload.metrics["average_score"], 91.5)
        self.assertEqual(result.metadata.subject, "数学")

    def test_adapted_result_is_saved(self):
        store = ResultStore()
        request = self.make_request()

        result = get_or_build_report_result(
            request,
            store,
            self.make_legacy_result(),
        )

        self.assertTrue(store.exists(build_result_key(request)))
        self.assertEqual(store.get(build_result_key(request)), result)

    def test_second_request_reuses_cache_instead_of_new_legacy_result(self):
        store = ResultStore()
        request = self.make_request()
        first = get_or_build_report_result(
            request,
            store,
            self.make_legacy_result(average=91.5),
        )

        second = get_or_build_report_result(
            request,
            store,
            self.make_legacy_result(average=10.0),
        )

        self.assertEqual(second, first)
        self.assertEqual(second.payload.metrics["average_score"], 91.5)

    def test_missing_new_architecture_objects_use_legacy_fallback(self):
        legacy = self.make_legacy_result()

        result = get_or_build_report_result(None, None, legacy)
        report_payload = analysis_result_to_legacy_dict(
            result,
            fallback=legacy,
        )

        self.assertIsNone(result)
        self.assertEqual(report_payload, legacy)
        self.assertIsNot(report_payload, legacy)

    def test_legacy_dict_round_trip_is_lossless(self):
        legacy = self.make_legacy_result()
        original = deepcopy(legacy)

        result = get_or_build_report_result(
            self.make_request(),
            ResultStore(),
            legacy,
        )
        round_trip = analysis_result_to_legacy_dict(result, fallback={})

        self.assertEqual(round_trip, original)
        self.assertEqual(legacy, original)


if __name__ == "__main__":
    unittest.main()
