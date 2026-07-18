from copy import deepcopy
import unittest

from models import ExamConfig, PageState, SubjectConfig
from services.config_resolver import effective_config


class ConfigResolverTest(unittest.TestCase):
    def setUp(self):
        self.exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    excellent_percent=90.0,
                    pass_percent=60.0,
                ),
                "英语": SubjectConfig(
                    full_score=150.0,
                    excellent_percent=85.0,
                    pass_percent=60.0,
                ),
            },
        )
        self.system_default = SubjectConfig(
            full_score=100.0,
            excellent_percent=90.0,
            pass_percent=60.0,
        )

    def test_page_state_override_has_highest_priority(self):
        page_state = PageState(
            exam_id="exam-1",
            page_name="subject_analysis",
            config_overrides={"数学": {"excellent_percent": 85.0}},
        )

        resolved = effective_config(
            self.exam_config,
            page_state,
            "数学",
            self.system_default,
        )

        self.assertEqual(resolved.excellent_percent, 85.0)

    def test_exam_config_is_used_without_page_override(self):
        resolved = effective_config(
            self.exam_config,
            PageState(exam_id="exam-1", page_name="grade_overview"),
            "英语",
            self.system_default,
        )

        self.assertEqual(resolved.full_score, 150.0)
        self.assertEqual(resolved.excellent_percent, 85.0)

    def test_system_default_is_used_without_exam_config(self):
        resolved = effective_config(
            None,
            PageState(exam_id="exam-1", page_name="grade_overview"),
            "数学",
            self.system_default,
        )

        self.assertEqual(resolved, self.system_default)
        self.assertIsNot(resolved, self.system_default)

    def test_override_falls_back_to_exam_config_field_by_field(self):
        page_state = PageState(
            exam_id="exam-1",
            page_name="subject_analysis",
            config_overrides={"数学": {"excellent_percent": 85.0}},
        )

        resolved = effective_config(
            self.exam_config,
            page_state,
            "数学",
            self.system_default,
        )

        self.assertEqual(resolved.full_score, 120.0)
        self.assertEqual(resolved.pass_percent, 60.0)
        self.assertEqual(resolved.excellent_percent, 85.0)

    def test_resolver_does_not_modify_inputs(self):
        page_state = PageState(
            exam_id="exam-1",
            page_name="subject_analysis",
            config_overrides={"数学": {"excellent_percent": 85.0}},
        )
        original_exam_config = deepcopy(self.exam_config)
        original_page_state = deepcopy(page_state)
        original_default = deepcopy(self.system_default)

        effective_config(
            self.exam_config,
            page_state,
            "数学",
            self.system_default,
        )

        self.assertEqual(self.exam_config, original_exam_config)
        self.assertEqual(page_state, original_page_state)
        self.assertEqual(self.system_default, original_default)

    def test_page_state_from_another_exam_cannot_override_config(self):
        other_exam_page = PageState(
            exam_id="exam-2",
            page_name="subject_analysis",
            config_overrides={"数学": {"excellent_percent": 70.0}},
        )

        resolved = effective_config(
            self.exam_config,
            other_exam_page,
            "数学",
            self.system_default,
        )

        self.assertEqual(resolved.excellent_percent, 90.0)

    def test_subject_overrides_are_isolated(self):
        page_state = PageState(
            exam_id="exam-1",
            page_name="subject_analysis",
            config_overrides={"数学": {"excellent_percent": 80.0}},
        )

        math_config = effective_config(
            self.exam_config,
            page_state,
            "数学",
            self.system_default,
        )
        english_config = effective_config(
            self.exam_config,
            page_state,
            "英语",
            self.system_default,
        )

        self.assertEqual(math_config.full_score, 120.0)
        self.assertEqual(math_config.excellent_percent, 80.0)
        self.assertEqual(english_config.full_score, 150.0)
        self.assertEqual(english_config.excellent_percent, 85.0)


if __name__ == "__main__":
    unittest.main()
