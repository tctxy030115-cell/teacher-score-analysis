from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from models import (
    AnalysisRules,
    ExamConfig,
    ExamContext,
    ExamMetadata,
    ExamSchema,
    PageState,
    SubjectConfig,
)
from services.request_builder import build_analysis_request


class AnalysisRequestBuilderTest(unittest.TestCase):
    def make_context(self, exam_id="exam-1"):
        return ExamContext(
            exam_id=exam_id,
            metadata=ExamMetadata(
                file_name="期中考试.xlsx",
                file_fingerprint="fingerprint",
                sheet_name="成绩表",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                score_columns=("数学", "英语"),
            ),
        )

    def make_config(self, exam_id="exam-1", version=3):
        return ExamConfig(
            exam_id=exam_id,
            version=version,
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    excellent_percent=90.0,
                ),
                "英语": SubjectConfig(
                    full_score=150.0,
                    excellent_percent=85.0,
                ),
            },
            rules=AnalysisRules(
                pass_percent=60.0,
                excellent_percent=90.0,
                levels={"excellent": 90.0, "good": 80.0, "pass": 60.0},
            ),
        )

    def make_page_state(
        self,
        *,
        exam_id="exam-1",
        subject="数学",
        classes=("2401", "2402"),
        overrides=None,
    ):
        return PageState(
            exam_id=exam_id,
            page_name="subject_analysis",
            selected_subject=subject,
            selected_classes=classes,
            config_overrides=overrides or {},
        )

    def build(self, context=None, config=None, page_state=None):
        return build_analysis_request(
            context or self.make_context(),
            config or self.make_config(),
            page_state or self.make_page_state(),
        )

    def test_same_inputs_generate_same_request(self):
        context = self.make_context()
        config = self.make_config()
        page_state = self.make_page_state()

        first = self.build(context, config, page_state)
        second = self.build(context, config, page_state)

        self.assertEqual(first, second)
        self.assertEqual(first.exam_id, "exam-1")
        self.assertEqual(first.page_name, "subject_analysis")
        self.assertEqual(first.analysis_type, "subject_analysis")
        self.assertEqual(first.config_version, 3)

    def test_different_subjects_generate_different_requests(self):
        math_request = self.build(page_state=self.make_page_state(subject="数学"))
        english_request = self.build(page_state=self.make_page_state(subject="英语"))

        self.assertNotEqual(math_request, english_request)

    def test_different_class_sets_generate_different_requests(self):
        first = self.build(page_state=self.make_page_state(classes=("2401",)))
        second = self.build(
            page_state=self.make_page_state(classes=("2401", "2402"))
        )

        self.assertNotEqual(first, second)

    def test_class_order_is_normalized(self):
        first = self.build(
            page_state=self.make_page_state(classes=("2402", "2401"))
        )
        second = self.build(
            page_state=self.make_page_state(classes=("2401", "2402"))
        )

        self.assertEqual(first, second)
        self.assertEqual(first.selected_classes, ("2401", "2402"))

    def test_relevant_override_changes_request(self):
        original = self.build(page_state=self.make_page_state())
        changed = self.build(
            page_state=self.make_page_state(
                overrides={"数学": {"excellent_percent": 85.0}}
            )
        )

        self.assertNotEqual(original, changed)
        self.assertNotEqual(original.state_signature, changed.state_signature)

    def test_unrelated_subject_override_does_not_change_request(self):
        original = self.build(page_state=self.make_page_state(subject="数学"))
        unrelated = self.build(
            page_state=self.make_page_state(
                subject="数学",
                overrides={"英语": {"excellent_percent": 80.0}},
            )
        )

        self.assertEqual(original, unrelated)

    def test_builder_does_not_modify_inputs(self):
        context = self.make_context()
        config = self.make_config()
        page_state = self.make_page_state(
            classes=("2402", "2401"),
            overrides={"数学": {"excellent_percent": 85.0}},
        )
        original_context = deepcopy(context)
        original_config = deepcopy(config)
        original_page_state = deepcopy(page_state)

        self.build(context, config, page_state)

        self.assertEqual(context, original_context)
        self.assertEqual(config, original_config)
        self.assertEqual(page_state, original_page_state)

    def test_cross_exam_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "exam_id"):
            self.build(page_state=self.make_page_state(exam_id="exam-2"))

    def test_request_is_frozen_and_contains_no_exam_data(self):
        request = self.build()

        with self.assertRaises(FrozenInstanceError):
            request.subject = "英语"
        for forbidden_attribute in (
            "identity_records_by_index",
            "subject_scores_by_index",
            "excel_content",
            "figure",
            "result",
        ):
            self.assertFalse(hasattr(request, forbidden_attribute))


if __name__ == "__main__":
    unittest.main()
