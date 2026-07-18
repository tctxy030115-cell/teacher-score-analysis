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
from services.class_analysis_service import get_or_build_class_result


class ClassAnalysisServiceTest(unittest.TestCase):
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
            identity_records_by_index={
                7: {
                    "identity_key": ("class_name", "2401", "张三"),
                    "姓名": "张三",
                    "班级": "2401",
                    "学号": "",
                },
                9: {
                    "identity_key": ("class_name", "2402", "张三"),
                    "姓名": "张三",
                    "班级": "2402",
                    "学号": "",
                },
            },
            subject_scores_by_index={
                7: {"数学": 91.0, "英语": 88.0},
                9: {"数学": 87.0, "英语": 90.0},
            },
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

    def make_page_state(
        self,
        *,
        subject="数学",
        classes=("2401", "2402"),
        overrides=None,
    ):
        return PageState(
            exam_id="exam-1",
            page_name="class_comparison",
            selected_subject=subject,
            selected_classes=classes,
            config_overrides=overrides or {},
        )

    def make_legacy_result(self, subject="数学"):
        class_rows = [
            {
                "班级": "2401",
                "有效人数": 1,
                "平均分": 91.0,
                "平均得分率": 75.8,
                "及格率": 100.0,
                "优秀率": 0.0,
            },
            {
                "班级": "2402",
                "有效人数": 1,
                "平均分": 87.0,
                "平均得分率": 72.5,
                "及格率": 100.0,
                "优秀率": 0.0,
            },
        ]
        level_rows = [
            {"班级": "2401", "等级": "良好", "人数": 1, "占比": 100.0},
            {"班级": "2402", "等级": "良好", "人数": 1, "占比": 100.0},
        ]
        return {
            "summary": {
                "current_subject": subject,
                "selected_classes": ("2401", "2402"),
            },
            "metrics": {
                "class_count": 2,
                "student_count": 2,
                "class_metrics": class_rows,
            },
            "tables": {
                "class_comparison": class_rows,
                "level_structure": level_rows,
                "excluded_classes": [],
            },
            "charts": {
                "average_rate_data": class_rows,
                "pass_excellent_data": class_rows,
                "level_structure_data": level_rows,
            },
            "extra": {},
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
        return get_or_build_class_result(
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

        self.assertEqual(calls, [True])
        self.assertTrue(store.exists(result.result_key))
        self.assertEqual(store.get(result.result_key), result)

    def test_cache_hit_does_not_recalculate(self):
        store = ResultStore()
        first = self.call_service(store=store)

        second = self.call_service(
            store=store,
            callback=lambda: self.fail("缓存命中时不应重新计算"),
        )

        self.assertEqual(second, first)

    def test_class_sets_generate_different_result_keys(self):
        first = self.call_service(
            page_state=self.make_page_state(classes=("2401", "2402"))
        )
        second = self.call_service(
            page_state=self.make_page_state(classes=("2402", "2403"))
        )

        self.assertNotEqual(first.result_key, second.result_key)

    def test_subjects_generate_different_result_keys(self):
        math = self.call_service(page_state=self.make_page_state(subject="数学"))
        english = self.call_service(
            page_state=self.make_page_state(subject="英语")
        )

        self.assertNotEqual(math.result_key, english.result_key)

    def test_full_score_override_does_not_modify_exam_config(self):
        config = self.make_config()
        original = deepcopy(config)

        self.call_service(
            config=config,
            page_state=self.make_page_state(
                overrides={"数学": {"full_score": 130.0}}
            ),
        )

        self.assertEqual(config, original)
        self.assertEqual(config.subjects["数学"].full_score, 120.0)

    def test_excellent_override_does_not_modify_exam_config(self):
        config = self.make_config()
        original = deepcopy(config)

        self.call_service(
            config=config,
            page_state=self.make_page_state(
                overrides={"数学": {"excellent_percent": 88.0}}
            ),
        )

        self.assertEqual(config, original)
        self.assertEqual(config.subjects["数学"].excellent_percent, 90.0)

    def test_callback_keeps_original_indexes_for_duplicate_names(self):
        context = self.make_context()
        observed_indexes = []

        def calculate():
            observed_indexes.extend(context.identity_records_by_index)
            self.assertEqual(
                context.identity_records_by_index[7]["identity_key"],
                ("class_name", "2401", "张三"),
            )
            self.assertEqual(
                context.identity_records_by_index[9]["identity_key"],
                ("class_name", "2402", "张三"),
            )
            return self.make_legacy_result()

        self.call_service(context=context, callback=calculate)

        self.assertEqual(observed_indexes, [7, 9])

    def test_missing_new_architecture_object_returns_none_without_callback(self):
        calls = []

        result = get_or_build_class_result(
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

    def test_result_payload_contains_metrics_tables_and_chart_data(self):
        result = self.call_service()

        self.assertIsInstance(result.payload, ResultPayload)
        self.assertEqual(result.payload.metrics["class_count"], 2)
        self.assertIn("class_comparison", result.payload.tables)
        self.assertIn("level_structure", result.payload.tables)
        self.assertIn("average_rate_data", result.payload.charts)
        self.assertIn("level_structure_data", result.payload.charts)


if __name__ == "__main__":
    unittest.main()
