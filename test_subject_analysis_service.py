from copy import deepcopy
import unittest

from models import (
    ExamConfig,
    ExamContext,
    ExamMetadata,
    ExamSchema,
    PageState,
    ResultPayload,
    SubjectConfig,
)
from services import ResultStore
from services.subject_analysis_service import get_or_build_subject_result


class SubjectAnalysisServiceTest(unittest.TestCase):
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

    def make_config(self, exam_id="exam-1"):
        return ExamConfig(
            exam_id=exam_id,
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
        )

    def make_page_state(self, subject="数学", overrides=None):
        return PageState(
            exam_id="exam-1",
            page_name="subject_analysis",
            selected_subject=subject,
            selected_classes=("2401", "2402"),
            config_overrides=overrides or {},
        )

    def make_legacy_result(self, subject="数学", average=91.5):
        return {
            "summary": {
                "current_subject": subject,
                "analysis_scope": "全部学生",
            },
            "metrics": {
                "student_count": 2,
                "average_score": average,
                "highest_score": 98.0,
                "lowest_score": 85.0,
                "pass_rate": 100.0,
                "excellent_rate": 50.0,
            },
            "tables": {
                "class_comparison": [{"班级": "2401", "平均分": 91.5}],
                "score_details": [["张三", 98.0]],
                "student_lists": {"excellent": ["张三"]},
            },
            "charts": {
                "class_average_rate_data": [{"班级": "2401", "平均得分率": 76.25}],
                "level_structure_data": [{"班级": "2401", "等级": "优秀"}],
            },
            "extra": {"invalid_warning": ""},
        }

    def call_service(
        self,
        *,
        context=None,
        config=None,
        page_state=None,
        store=None,
        callback=None,
    ):
        return get_or_build_subject_result(
            context if context is not None else self.make_context(),
            config if config is not None else self.make_config(),
            page_state if page_state is not None else self.make_page_state(),
            store if store is not None else ResultStore(),
            callback if callback is not None else self.make_legacy_result,
        )

    def test_first_request_calculates_and_saves_result(self):
        store = ResultStore()
        calls = []

        def calculate():
            calls.append(True)
            return self.make_legacy_result()

        result = self.call_service(store=store, callback=calculate)

        self.assertEqual(len(calls), 1)
        self.assertTrue(store.exists(result.result_key))
        self.assertEqual(store.get(result.result_key), result)

    def test_cache_hit_returns_without_recalculation(self):
        store = ResultStore()
        calls = []

        def calculate():
            calls.append(True)
            return self.make_legacy_result(average=91.5)

        first = self.call_service(store=store, callback=calculate)
        second = self.call_service(
            store=store,
            callback=lambda: self.fail("缓存命中时不应重新计算"),
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(second, first)

    def test_subjects_and_relevant_overrides_have_distinct_result_keys(self):
        math = self.call_service(page_state=self.make_page_state("数学"))
        english = self.call_service(page_state=self.make_page_state("英语"))
        math_override = self.call_service(
            page_state=self.make_page_state(
                "数学",
                {"数学": {"full_score": 130.0}},
            )
        )

        self.assertNotEqual(math.result_key, english.result_key)
        self.assertNotEqual(math.result_key, math_override.result_key)

    def test_config_overrides_do_not_modify_exam_config(self):
        config = self.make_config()
        page_state = self.make_page_state(
            overrides={
                "数学": {
                    "full_score": 130.0,
                    "excellent_percent": 88.0,
                }
            }
        )
        original_config = deepcopy(config)

        self.call_service(config=config, page_state=page_state)

        self.assertEqual(config, original_config)
        self.assertEqual(config.subjects["数学"].full_score, 120.0)
        self.assertEqual(config.subjects["数学"].excellent_percent, 90.0)

    def test_missing_new_architecture_object_returns_none_without_calculation(self):
        calls = []

        result = get_or_build_subject_result(
            None,
            self.make_config(),
            self.make_page_state(),
            ResultStore(),
            lambda: calls.append(True),
        )

        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_service_does_not_modify_inputs(self):
        context = self.make_context()
        config = self.make_config()
        page_state = self.make_page_state(
            overrides={"数学": {"excellent_percent": 88.0}}
        )
        original_context = deepcopy(context)
        original_config = deepcopy(config)
        original_page_state = deepcopy(page_state)

        self.call_service(
            context=context,
            config=config,
            page_state=page_state,
        )

        self.assertEqual(context, original_context)
        self.assertEqual(config, original_config)
        self.assertEqual(page_state, original_page_state)

    def test_result_payload_keeps_all_subject_result_sections(self):
        result = self.call_service()

        self.assertIsInstance(result.payload, ResultPayload)
        self.assertEqual(result.payload.summary["current_subject"], "数学")
        self.assertEqual(result.payload.metrics["average_score"], 91.5)
        self.assertIn("class_comparison", result.payload.tables)
        self.assertIn("class_average_rate_data", result.payload.charts)
        self.assertIn("invalid_warning", result.payload.extra)


if __name__ == "__main__":
    unittest.main()
