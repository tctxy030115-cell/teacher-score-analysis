from copy import deepcopy
import unittest

from models import ExamConfig, SubjectConfig
from services import build_exam_context
from services.exam_config_builder import build_exam_config


class ExamConfigBuilderTest(unittest.TestCase):
    def setUp(self):
        self.context = build_exam_context(
            file_content=b"exam workbook",
            file_name="期中考试.xlsx",
            sheet_name="成绩表",
            exam_name="2026年期中考试",
            name_column="姓名",
            class_column="班级",
            student_id_column="学号",
            score_columns=("数学", "英语"),
            identity_records_by_index={
                3: {"identity_key": ("student_id", "1001"), "姓名": "张三"},
            },
            subject_scores_by_index={3: {"数学": 118, "英语": 145}},
        )
        self.snapshot = {
            "score_col": "数学",
            "full_score": 120.0,
            "excellent_percent": 90.0,
            "full_score_by_column": {"数学": 120.0, "英语": 150.0},
            "analysis_result": {"student_count": 1},
        }

    def build_config(self, **overrides):
        arguments = {
            "exam_context": self.context,
            "snapshot": self.snapshot,
            "full_score_by_subject": {"数学": 120.0, "英语": 150.0},
            "excellent_percent_by_subject": {"数学": 90.0, "英语": 85.0},
        }
        arguments.update(overrides)
        return build_exam_config(**arguments)

    def test_same_exam_rules_generate_stable_exam_config(self):
        first = self.build_config()
        second = self.build_config()

        self.assertIsInstance(first, ExamConfig)
        self.assertEqual(first, second)
        self.assertEqual(first.exam_id, self.context.exam_id)
        self.assertEqual(first.version, 1)

    def test_subjects_keep_independent_full_scores(self):
        config = self.build_config()

        self.assertEqual(config.subjects["数学"].full_score, 120.0)
        self.assertEqual(config.subjects["英语"].full_score, 150.0)

    def test_subjects_keep_independent_excellent_percentages(self):
        config = self.build_config()

        self.assertEqual(config.subjects["数学"].excellent_percent, 90.0)
        self.assertEqual(config.subjects["英语"].excellent_percent, 85.0)

    def test_each_subject_uses_fixed_sixty_percent_pass_rule(self):
        config = self.build_config()

        self.assertEqual(config.subjects["数学"].pass_percent, 60.0)
        self.assertEqual(config.subjects["英语"].pass_percent, 60.0)
        self.assertEqual(config.rules.pass_percent, 60.0)

    def test_builder_does_not_modify_snapshot_or_context(self):
        original_snapshot = deepcopy(self.snapshot)
        original_context = deepcopy(self.context)

        self.build_config()

        self.assertEqual(self.snapshot, original_snapshot)
        self.assertEqual(self.context, original_context)

    def test_config_contains_rules_only(self):
        config = self.build_config()

        for forbidden_attribute in (
            "selected_subject",
            "selected_class",
            "identity_records_by_index",
            "subject_scores_by_index",
            "analysis_result",
        ):
            self.assertFalse(hasattr(config, forbidden_attribute))

    def test_invalid_build_does_not_replace_existing_config(self):
        existing_config = ExamConfig(
            exam_id=self.context.exam_id,
            subjects={"数学": SubjectConfig(full_score=120.0)},
        )
        session_state = {"current_exam_config": existing_config}

        try:
            candidate = self.build_config(config_version=0)
        except (TypeError, ValueError):
            candidate = session_state.get("current_exam_config")
        if candidate is not None:
            session_state["current_exam_config"] = candidate

        self.assertIs(session_state["current_exam_config"], existing_config)


if __name__ == "__main__":
    unittest.main()
