from dataclasses import replace
import re
import unittest

from models import AnalysisRequest, ResultKey
from services.result_key_builder import build_result_key


class ResultKeyBuilderTest(unittest.TestCase):
    def make_request(self, **changes):
        request = AnalysisRequest(
            exam_id="exam-1",
            page_name="subject_analysis",
            analysis_type="subject_analysis",
            subject="数学",
            selected_classes=("2401", "2402"),
            config_version=3,
            config_signature="a" * 64,
            state_signature="b" * 64,
        )
        return replace(request, **changes)

    def test_same_request_generates_stable_key(self):
        request = self.make_request()

        first = build_result_key(request)
        second = build_result_key(request)

        self.assertEqual(first, second)
        self.assertEqual(first.exam_id, request.exam_id)
        self.assertEqual(first.analysis_type, request.analysis_type)
        self.assertEqual(first.config_version, request.config_version)
        self.assertIsInstance(first.request_signature, str)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", first.request_signature))

    def test_subject_changes_key(self):
        self.assertNotEqual(
            build_result_key(self.make_request(subject="数学")),
            build_result_key(self.make_request(subject="英语")),
        )

    def test_class_scope_changes_key(self):
        self.assertNotEqual(
            build_result_key(self.make_request(selected_classes=("2401",))),
            build_result_key(
                self.make_request(selected_classes=("2401", "2402"))
            ),
        )

    def test_config_version_changes_key(self):
        self.assertNotEqual(
            build_result_key(self.make_request(config_version=3)),
            build_result_key(self.make_request(config_version=4)),
        )

    def test_override_signature_changes_key(self):
        self.assertNotEqual(
            build_result_key(self.make_request(state_signature="b" * 64)),
            build_result_key(self.make_request(state_signature="c" * 64)),
        )

    def test_different_exams_are_isolated(self):
        self.assertNotEqual(
            build_result_key(self.make_request(exam_id="exam-1")),
            build_result_key(self.make_request(exam_id="exam-2")),
        )

    def test_legacy_result_key_constructor_remains_compatible(self):
        legacy_signature = (("selected_subject", "数学"),)
        key = ResultKey(
            exam_id="exam-1",
            config_version=1,
            analysis_type="grade_overview",
            request_signature=legacy_signature,
        )

        self.assertEqual(key.request_signature, legacy_signature)


if __name__ == "__main__":
    unittest.main()
