from copy import deepcopy
from datetime import datetime, timezone
import unittest

from models import (
    AnalysisResult,
    ResultKey,
    ResultMetadata,
    ResultPayload,
)
from services.result_adapter import adapt_analysis_result


class ResultAdapterTest(unittest.TestCase):
    def make_key(self, signature_character="a"):
        return ResultKey(
            exam_id="exam-1",
            config_version=2,
            analysis_type="grade_overview",
            request_signature=signature_character * 64,
        )

    def make_legacy_result(self):
        return {
            "current_class": "全部学生",
            "current_subject": "数学",
            "student_count": 2,
            "average_score": 91.5,
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
            "distribution_figure": {"kind": "distribution"},
            "trend_chart": {"kind": "trend"},
            "charts": {"level": {"kind": "level"}},
            "legacy_note": {"text": "保留未知字段"},
        }

    def test_legacy_dict_converts_to_structured_analysis_result(self):
        result = adapt_analysis_result(
            self.make_key(),
            self.make_legacy_result(),
        )

        self.assertIsInstance(result, AnalysisResult)
        self.assertIsInstance(result.payload, ResultPayload)
        self.assertEqual(result.result_key, self.make_key())
        self.assertEqual(result.key, result.result_key)

    def test_result_contains_metadata(self):
        created_at = datetime(2026, 7, 17, tzinfo=timezone.utc)

        result = adapt_analysis_result(
            self.make_key(),
            self.make_legacy_result(),
            created_at=created_at,
        )

        self.assertEqual(result.metadata.exam_id, "exam-1")
        self.assertEqual(result.metadata.analysis_type, "grade_overview")
        self.assertEqual(result.metadata.subject, "数学")
        self.assertEqual(result.metadata.created_at, created_at)

    def test_metrics_are_classified(self):
        result = adapt_analysis_result(
            self.make_key(),
            self.make_legacy_result(),
        )

        self.assertEqual(result.payload.metrics["average_score"], 91.5)
        self.assertEqual(result.payload.metrics["student_count"], 2)
        self.assertEqual(result.payload.metrics["pass_rate"], 100.0)
        self.assertEqual(result.payload.metrics["full_score"], 120.0)
        self.assertEqual(result.payload.metrics["excellent_percent"], 90.0)

    def test_tables_are_classified(self):
        result = adapt_analysis_result(
            self.make_key(),
            self.make_legacy_result(),
        )

        self.assertEqual(
            result.payload.tables["score_details"],
            [["张三", 98.0, "优秀"]],
        )
        self.assertEqual(
            result.payload.tables["excellent_students"],
            [["张三", 98.0]],
        )
        self.assertEqual(result.payload.tables["fail_students"], [])

    def test_charts_are_classified_and_explicit_container_is_merged(self):
        result = adapt_analysis_result(
            self.make_key(),
            self.make_legacy_result(),
        )

        self.assertEqual(
            result.payload.charts["distribution_figure"],
            {"kind": "distribution"},
        )
        self.assertEqual(
            result.payload.charts["trend_chart"],
            {"kind": "trend"},
        )
        self.assertEqual(
            result.payload.charts["level"],
            {"kind": "level"},
        )

    def test_unknown_fields_are_preserved_in_extra(self):
        result = adapt_analysis_result(
            self.make_key(),
            self.make_legacy_result(),
        )

        self.assertEqual(
            result.payload.extra["legacy_note"],
            {"text": "保留未知字段"},
        )

    def test_adapter_deep_copies_input(self):
        legacy_result = self.make_legacy_result()
        original = deepcopy(legacy_result)
        result = adapt_analysis_result(self.make_key(), legacy_result)

        legacy_result["score_details"][0][1] = 0.0
        legacy_result["legacy_note"]["text"] = "已修改"
        legacy_result["charts"]["level"]["kind"] = "changed"

        self.assertEqual(
            result.payload.tables["score_details"],
            original["score_details"],
        )
        self.assertEqual(
            result.payload.extra["legacy_note"],
            original["legacy_note"],
        )
        self.assertEqual(
            result.payload.charts["level"],
            original["charts"]["level"],
        )

    def test_different_result_keys_generate_different_results(self):
        first = adapt_analysis_result(
            self.make_key("a"),
            self.make_legacy_result(),
        )
        second = adapt_analysis_result(
            self.make_key("b"),
            self.make_legacy_result(),
        )

        self.assertNotEqual(first, second)

    def test_empty_result_is_stable(self):
        result = adapt_analysis_result(self.make_key(), {})

        self.assertEqual(result.metadata.subject, None)
        self.assertEqual(result.payload.summary, {})
        self.assertEqual(result.payload.metrics, {})
        self.assertEqual(result.payload.tables, {})
        self.assertEqual(result.payload.charts, {})
        self.assertEqual(result.payload.extra, {})

    def test_payload_default_containers_are_independent(self):
        first = ResultPayload()
        second = ResultPayload()

        first.metrics["average_score"] = 90.0
        first.tables["details"] = []

        self.assertNotIn("average_score", second.metrics)
        self.assertNotIn("details", second.tables)

    def test_new_and_legacy_analysis_result_constructors_are_supported(self):
        key = self.make_key()
        metadata = ResultMetadata(
            exam_id="exam-1",
            analysis_type="grade_overview",
            subject="数学",
        )
        payload = ResultPayload(metrics={"average_score": 91.5})

        structured = AnalysisResult(
            result_key=key,
            metadata=metadata,
            payload=payload,
        )
        legacy = AnalysisResult(
            key=key,
            payload={"average_score": 91.5},
        )

        self.assertEqual(structured.key, key)
        self.assertIs(structured.payload, payload)
        self.assertEqual(legacy.result_key, key)
        self.assertEqual(legacy.payload["average_score"], 91.5)
        self.assertEqual(legacy.metadata.exam_id, "exam-1")


if __name__ == "__main__":
    unittest.main()
