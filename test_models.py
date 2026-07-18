import unittest

from models import (
    AnalysisResult,
    AnalysisRules,
    ClassAnalysisState,
    ExamConfig,
    ExamContext,
    ExamMetadata,
    ExamPageState,
    ExamSchema,
    GradeOverviewState,
    PageState,
    ReportCenterState,
    ResultKey,
    SubjectAnalysisState,
    SubjectConfig,
)


class DataModelTest(unittest.TestCase):
    def test_exam_context_keeps_exam_data_separate_from_page_choices(self):
        context = ExamContext(
            exam_id="exam-2026-midterm",
            metadata=ExamMetadata(
                file_name="期中考试.xlsx",
                file_fingerprint="abc123",
                sheet_name="成绩表",
                exam_name="2026年期中考试",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                student_id_column="学号",
                score_columns=("数学", "英语"),
            ),
            identity_records_by_index={
                7: {"identity_key": ("student_id", "1001"), "姓名": "张三"},
            },
            subject_scores_by_index={7: {"数学": 118, "英语": 145}},
        )

        self.assertEqual(context.exam_id, "exam-2026-midterm")
        self.assertEqual(context.schema.score_columns, ("数学", "英语"))
        self.assertEqual(context.identity_records_by_index[7]["姓名"], "张三")
        self.assertFalse(hasattr(context, "selected_subject"))
        self.assertFalse(hasattr(context, "selected_class"))

    def test_exam_context_default_mappings_are_not_shared(self):
        metadata = ExamMetadata(
            file_name="考试.xlsx",
            file_fingerprint="fingerprint",
            sheet_name="成绩表",
        )
        schema = ExamSchema(name_column="姓名", score_columns=("数学",))

        first = ExamContext("exam-1", metadata, schema)
        second = ExamContext("exam-2", metadata, schema)

        self.assertIsNot(first.identity_records_by_index, second.identity_records_by_index)
        self.assertIsNot(first.subject_scores_by_index, second.subject_scores_by_index)

    def test_exam_context_requires_an_exam_id(self):
        metadata = ExamMetadata(
            file_name="考试.xlsx",
            file_fingerprint="fingerprint",
            sheet_name="成绩表",
        )
        schema = ExamSchema(name_column="姓名", score_columns=("数学",))

        with self.assertRaises(ValueError):
            ExamContext(" ", metadata, schema)

    def test_exam_config_keeps_subject_rules_and_page_overrides_separate(self):
        config = ExamConfig(
            exam_id="exam-1",
            version=3,
            subjects={
                "数学": SubjectConfig(full_score=120.0),
                "英语": SubjectConfig(full_score=150.0),
            },
            rules=AnalysisRules(
                pass_percent=60.0,
                excellent_percent=90.0,
            ),
            page_overrides={
                "subject_analysis": {
                    "英语": SubjectConfig(full_score=150.0, excellent_percent=85.0),
                }
            },
        )

        self.assertEqual(config.subjects["数学"].full_score, 120.0)
        self.assertEqual(config.rules.pass_percent, 60.0)
        self.assertEqual(
            config.page_overrides["subject_analysis"]["英语"].excellent_percent,
            85.0,
        )

    def test_exam_config_requires_positive_version(self):
        with self.assertRaises(ValueError):
            ExamConfig(exam_id="exam-1", version=0)

    def test_subject_config_keeps_old_constructor_compatible_with_default_pass_rule(self):
        subject = SubjectConfig(full_score=120.0, excellent_percent=85.0)

        self.assertEqual(subject.full_score, 120.0)
        self.assertEqual(subject.excellent_percent, 85.0)
        self.assertEqual(subject.pass_percent, 60.0)

    def test_page_state_is_namespaced_by_exam(self):
        first_exam_state = ExamPageState(
            grade_overview=GradeOverviewState(
                selected_subject="数学",
                selected_class="1班",
            ),
            subject_analysis=SubjectAnalysisState(selected_subject="英语"),
            class_analysis=ClassAnalysisState(
                selected_subject="数学",
                selected_classes=("1班", "2班"),
            ),
            report_center=ReportCenterState(
                school_name="示例学校",
                report_title="期中考试分析",
            ),
        )
        page_state = PageState(
            route="analysis_center",
            by_exam={"exam-1": first_exam_state},
        )

        page_state.by_exam["exam-2"] = ExamPageState(
            grade_overview=GradeOverviewState(selected_subject="语文")
        )

        self.assertEqual(
            page_state.by_exam["exam-1"].grade_overview.selected_subject,
            "数学",
        )
        self.assertEqual(
            page_state.by_exam["exam-2"].grade_overview.selected_subject,
            "语文",
        )
        self.assertEqual(page_state.by_exam["exam-1"].class_analysis.selected_classes, ("1班", "2班"))

    def test_page_state_default_exam_mapping_is_not_shared(self):
        first = PageState()
        second = PageState()

        first.by_exam["exam-1"] = ExamPageState()

        self.assertNotIn("exam-1", second.by_exam)

    def test_page_state_adds_flat_parallel_record_without_breaking_legacy_fields(self):
        legacy_exam_state = ExamPageState()
        state = PageState(
            route="analysis_center",
            by_exam={"exam-1": legacy_exam_state},
            exam_id="exam-1",
            page_name="grade_overview",
            selected_subject="数学",
            selected_classes=["1班", "2班"],
            config_overrides={
                "数学": {"excellent_percent": 85.0},
            },
        )

        self.assertEqual(state.route, "analysis_center")
        self.assertIs(state.by_exam["exam-1"], legacy_exam_state)
        self.assertEqual(state.exam_id, "exam-1")
        self.assertEqual(state.page_name, "grade_overview")
        self.assertEqual(state.selected_subject, "数学")
        self.assertEqual(state.selected_classes, ("1班", "2班"))
        self.assertEqual(
            state.config_overrides["数学"]["excellent_percent"],
            85.0,
        )

    def test_page_state_parallel_mappings_are_not_shared(self):
        first = PageState(exam_id="exam-1", page_name="grade_overview")
        second = PageState(exam_id="exam-2", page_name="subject_analysis")

        first.config_overrides["数学"] = {"excellent_percent": 85.0}

        self.assertNotIn("数学", second.config_overrides)

    def test_result_key_distinguishes_config_versions(self):
        request_signature = (("selected_subject", "数学"), ("selected_class", "全部学生"))
        first = ResultKey(
            exam_id="exam-1",
            config_version=1,
            analysis_type="grade_overview",
            request_signature=request_signature,
        )
        same = ResultKey(
            exam_id="exam-1",
            config_version=1,
            analysis_type="grade_overview",
            request_signature=request_signature,
        )
        changed = ResultKey(
            exam_id="exam-1",
            config_version=2,
            analysis_type="grade_overview",
            request_signature=request_signature,
        )

        self.assertEqual(first, same)
        self.assertEqual(hash(first), hash(same))
        self.assertNotEqual(first, changed)

    def test_analysis_result_wraps_payload_without_page_state(self):
        key = ResultKey(
            exam_id="exam-1",
            config_version=1,
            analysis_type="subject_analysis",
        )
        result = AnalysisResult(key=key, payload={"average": 95.5})

        self.assertEqual(result.payload["average"], 95.5)
        self.assertFalse(hasattr(result, "selected_subject"))


if __name__ == "__main__":
    unittest.main()
