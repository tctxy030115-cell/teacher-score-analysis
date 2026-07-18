import ast
from copy import deepcopy
from pathlib import Path
import unittest

import pandas as pd

from grade_logic import analyze_scores
from models import ExamContext, ExamMetadata, ExamSchema
from services.grade_overview_context_adapter import (
    build_grade_overview_dataframe,
    build_grade_overview_identity_records,
)
from student_identity import (
    build_student_identity_records,
    build_student_score_mapping,
)


PROJECT_ROOT = Path(__file__).resolve().parent
ADAPTER_PATH = PROJECT_ROOT / "services" / "grade_overview_context_adapter.py"


def build_context() -> ExamContext:
    return ExamContext(
        exam_id="exam-grade-overview",
        metadata=ExamMetadata(
            file_name="期中考试.xlsx",
            file_fingerprint="fingerprint",
            sheet_name="成绩表",
            exam_name="期中考试",
        ),
        schema=ExamSchema(
            name_column="姓名",
            class_column="班级",
            student_id_column="学号",
            score_columns=("数学", "英语"),
        ),
        identity_records_by_index={
            10: {
                "identity_key": ("student_id", "1001"),
                "姓名": "张三",
                "班级": "2401",
                "学号": "1001",
                "分数": 0.0,
            },
            11: {
                "identity_key": ("student_id", "1002"),
                "姓名": "张三",
                "班级": "2402",
                "学号": "1002",
                "分数": 0.0,
            },
            12: {
                "identity_key": ("student_id", "1003"),
                "姓名": "李四",
                "班级": "2401",
                "学号": "1003",
                "分数": 0.0,
            },
        },
        subject_scores_by_index={
            10: {"数学": 118, "英语": 145},
            11: {"数学": 109, "英语": 138},
            12: {"数学": float("nan"), "英语": 130},
        },
    )


class GradeOverviewContextAdapterTest(unittest.TestCase):
    def test_context_builds_grade_overview_dataframe_with_original_index(self):
        dataframe = build_grade_overview_dataframe(build_context())

        self.assertEqual(list(dataframe.index), [10, 11, 12])
        self.assertEqual(
            list(dataframe.columns),
            ["学号", "班级", "姓名", "数学", "英语"],
        )
        self.assertEqual(dataframe.at[10, "数学"], 118)

    def test_adapter_does_not_modify_exam_context(self):
        context = build_context()
        original_identities = deepcopy(context.identity_records_by_index)
        original_scores = deepcopy(context.subject_scores_by_index)

        dataframe = build_grade_overview_dataframe(context)
        records = build_grade_overview_identity_records(
            context,
            "数学",
            dataframe.index[:2],
        )
        dataframe.at[10, "姓名"] = "已修改"
        records[0]["姓名"] = "也已修改"

        self.assertEqual(context.identity_records_by_index, original_identities)
        self.assertEqual(context.subject_scores_by_index, original_scores)

    def test_same_name_students_keep_distinct_identity_keys(self):
        records = build_grade_overview_identity_records(
            build_context(),
            "数学",
            [10, 11],
        )

        self.assertEqual([record["姓名"] for record in records], ["张三", "张三"])
        self.assertNotEqual(records[0]["identity_key"], records[1]["identity_key"])

    def test_cross_class_same_name_students_remain_independent(self):
        records = build_grade_overview_identity_records(
            build_context(),
            "数学",
            [10, 11],
        )
        mapping = build_student_score_mapping(records)

        self.assertEqual(len(mapping), 2)
        self.assertEqual(records[0]["班级"], "2401")
        self.assertEqual(records[1]["班级"], "2402")

    def test_missing_score_remains_nan_in_compatible_dataframe(self):
        dataframe = build_grade_overview_dataframe(build_context())

        self.assertTrue(pd.isna(dataframe.at[12, "数学"]))
        self.assertNotEqual(dataframe.at[12, "数学"], 0)

    def test_adapter_never_rebuilds_identity_or_matches_by_name(self):
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")

        self.assertNotIn("student_identity", imported_modules)
        self.assertNotIn("build_student_identity_records", source)
        self.assertNotIn("reset_index", source)
        self.assertNotIn("merge(", source)

    def test_context_and_legacy_paths_produce_same_analysis_result(self):
        context = build_context()
        dataframe = build_grade_overview_dataframe(context)
        valid_indices = [10, 11]

        legacy_rows = dataframe.loc[valid_indices, ["学号", "班级", "姓名"]].copy()
        legacy_rows["分数"] = dataframe.loc[valid_indices, "数学"].astype(float)
        legacy_records = build_student_identity_records(
            legacy_rows,
            class_column="班级",
            student_id_column="学号",
        )
        context_records = build_grade_overview_identity_records(
            context,
            "数学",
            valid_indices,
        )

        legacy_result = analyze_scores(
            build_student_score_mapping(legacy_records),
            full_score=120,
            excellent_percent=90,
            current_class="全部学生",
            current_subject="数学",
        )
        context_result = analyze_scores(
            build_student_score_mapping(context_records),
            full_score=120,
            excellent_percent=90,
            current_class="全部学生",
            current_subject="数学",
        )

        self.assertEqual(context_result, legacy_result)


if __name__ == "__main__":
    unittest.main()
