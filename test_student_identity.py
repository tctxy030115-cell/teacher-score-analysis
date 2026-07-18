from pathlib import Path
import unittest

import pandas as pd

from grade_logic import analyze_scores, export_score_result_to_bytes
from student_identity import (
    build_display_student_list,
    build_display_score_details,
    build_student_identity_records,
    build_student_score_mapping,
    find_student_id_column,
    restore_analysis_result_display_names,
)


class StudentIdentityTest(unittest.TestCase):
    def test_single_class_analysis_keeps_existing_result(self):
        valid_scores = pd.DataFrame(
            {
                "班级": ["2401", "2401"],
                "姓名": ["张三", "李四"],
                "分数": [90.0, 50.0],
            }
        )

        records = build_student_identity_records(
            valid_scores,
            class_column="班级",
        )
        result = analyze_scores(build_student_score_mapping(records))
        display_result = restore_analysis_result_display_names(result, records)

        self.assertEqual(result["student_count"], 2)
        self.assertEqual(result["pass_rate"], 50.0)
        self.assertEqual(
            display_result["score_details"],
            [["张三", 90.0, "优秀"], ["李四", 50.0, "不及格"]],
        )

    def test_same_name_in_multiple_classes_keeps_every_student(self):
        valid_scores = pd.DataFrame(
            {
                "班级": ["2401", "2402", "2403"],
                "姓名": ["张三", "张三", "张三"],
                "分数": [90.0, 60.0, 80.0],
            }
        )

        records = build_student_identity_records(
            valid_scores,
            class_column="班级",
        )
        scores = build_student_score_mapping(records)
        result = analyze_scores(scores)
        display_result = restore_analysis_result_display_names(result, records)

        self.assertEqual(
            [record["identity_key"] for record in records],
            [
                ("class_name", "2401", "张三"),
                ("class_name", "2402", "张三"),
                ("class_name", "2403", "张三"),
            ],
        )
        self.assertEqual(len(scores), 3)
        self.assertEqual(result["student_count"], 3)
        self.assertAlmostEqual(result["average_score"], 230 / 3)
        self.assertEqual(result["pass_rate"], 100.0)
        self.assertEqual(
            [detail[0] for detail in display_result["score_details"]],
            ["张三", "张三", "张三"],
        )

    def test_long_term_student_id_has_priority_and_is_preserved_for_display(self):
        valid_scores = pd.DataFrame(
            {
                "学号": [1001, 1002],
                "班级": ["2401", "2401"],
                "姓名": ["张三", "张三"],
                "分数": [90.0, 60.0],
            }
        )

        records = build_student_identity_records(
            valid_scores,
            class_column="班级",
            student_id_column="学号",
        )

        self.assertEqual(find_student_id_column(valid_scores.columns), "学号")
        self.assertEqual(records[0]["identity_key"], ("student_id", "1001"))
        self.assertEqual(
            records[0],
            {
                "identity_key": ("student_id", "1001"),
                "姓名": "张三",
                "班级": "2401",
                "学号": "1001",
                "分数": 90.0,
            },
        )
        self.assertEqual(len(build_student_score_mapping(records)), 2)

    def test_missing_student_id_falls_back_per_row(self):
        valid_scores = pd.DataFrame(
            {
                "学号": ["S1", "", ""],
                "班级": ["2401", "2402", ""],
                "姓名": ["张三", "李四", "王五"],
                "分数": [90.0, 80.0, 70.0],
            }
        )

        records = build_student_identity_records(
            valid_scores,
            class_column="班级",
            student_id_column="学号",
        )

        self.assertEqual(
            [record["identity_key"] for record in records],
            [
                ("student_id", "S1"),
                ("class_name", "2402", "李四"),
                ("name", "王五"),
            ],
        )

    def test_without_class_column_falls_back_to_name(self):
        valid_scores = pd.DataFrame(
            {"姓名": ["张三", "李四"], "分数": [90.0, 60.0]}
        )

        records = build_student_identity_records(valid_scores)

        self.assertEqual(records[0]["identity_key"], ("name", "张三"))
        self.assertEqual(records[0]["班级"], "")
        self.assertEqual(records[0]["学号"], "")

    def test_empty_name_is_rejected_before_identity_generation(self):
        invalid_scores = pd.DataFrame({"姓名": [""], "分数": [90.0]})

        with self.assertRaisesRegex(ValueError, "姓名为空"):
            build_student_identity_records(invalid_scores)

    def test_only_long_term_identity_aliases_are_recognized(self):
        for alias in ("学号", "学生学号", "学生编号", "学籍号"):
            self.assertEqual(find_student_id_column(["姓名", alias, "数学"]), alias)
        self.assertIsNone(find_student_id_column(["姓名", "考号", "准考证号", "数学"]))

    def test_duplicate_generated_identity_raises_instead_of_overwriting(self):
        records = build_student_identity_records(
            pd.DataFrame(
                {
                    "班级": ["2401", "2401"],
                    "姓名": ["张三", "张三"],
                    "分数": [90.0, 60.0],
                }
            ),
            class_column="班级",
        )

        with self.assertRaisesRegex(ValueError, "学生身份重复"):
            build_student_score_mapping(records)

    def test_details_and_lists_show_names_without_internal_identity_keys(self):
        records = build_student_identity_records(
            pd.DataFrame(
                {
                    "学号": ["S1", "S2"],
                    "班级": ["2401", "2402"],
                    "姓名": ["张三", "张三"],
                    "分数": [95.0, 50.0],
                }
            ),
            class_column="班级",
            student_id_column="学号",
        )
        result = analyze_scores(build_student_score_mapping(records))

        detail_rows = build_display_score_details(result, records)
        excellent_rows = build_display_student_list(
            result,
            records,
            result_key="excellent_students",
        )
        fail_rows = build_display_student_list(
            result,
            records,
            result_key="fail_students",
        )
        display_result = restore_analysis_result_display_names(result, records)

        self.assertEqual(detail_rows[0]["姓名"], "张三")
        self.assertEqual(detail_rows[0]["班级"], "2401")
        self.assertEqual(detail_rows[0]["学号"], "S1")
        self.assertNotIn("identity_key", detail_rows[0])
        self.assertEqual(
            excellent_rows[0],
            {"姓名": "张三", "班级": "2401", "学号": "S1", "分数": 95.0},
        )
        self.assertEqual(fail_rows[0]["班级"], "2402")
        self.assertNotIn("identity_key", excellent_rows[0])
        self.assertEqual(display_result["excellent_students"], [["张三", 95.0]])
        self.assertEqual(display_result["fail_students"], [["张三", 50.0]])
        self.assertTrue(
            all(not isinstance(row[0], tuple) for row in display_result["score_details"])
        )
        self.assertNotIn("student_identity_records", display_result)

    def test_export_and_report_names_distinguish_duplicate_students_without_tuple_keys(self):
        records = build_student_identity_records(
            pd.DataFrame(
                {
                    "班级": ["2401", "2402", "2403"],
                    "姓名": ["张三", "张三", "张三"],
                    "分数": [95.0, 50.0, 80.0],
                }
            ),
            class_column="班级",
        )
        result = analyze_scores(build_student_score_mapping(records))
        export_result = restore_analysis_result_display_names(
            result,
            records,
            contextualize_duplicate_names=True,
        )
        report_excellent = build_display_student_list(
            result,
            records,
            result_key="excellent_students",
            contextualize_duplicate_names=True,
        )
        report_fail = build_display_student_list(
            result,
            records,
            result_key="fail_students",
            contextualize_duplicate_names=True,
        )

        exported_details = pd.read_excel(
            export_score_result_to_bytes(export_result),
            sheet_name="成绩明细",
        )

        self.assertEqual(export_result["student_count"], 3)
        self.assertEqual(len(exported_details), 3)
        self.assertEqual(
            set(exported_details["姓名"]),
            {"张三（2401）", "张三（2402）", "张三（2403）"},
        )
        self.assertTrue(
            all(
                internal_text not in name
                for name in exported_details["姓名"]
                for internal_text in ("student_id", "class_name", "identity_key")
            )
        )
        self.assertEqual(report_excellent[0]["姓名"], "张三（2401）")
        self.assertEqual(report_fail[0]["姓名"], "张三（2402）")

    def test_app_no_longer_maps_students_or_classes_by_name_only(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertNotIn(
            'dict(zip(valid_scores["姓名"], valid_scores["分数"]))',
            source,
        )
        self.assertNotIn('set_index("姓名")', source)
        self.assertIn("build_student_identity_records(", source)
        self.assertIn("restore_analysis_result_display_names(", source)
        self.assertIn("report_excellent_df", source)
        self.assertIn("report_fail_df", source)


if __name__ == "__main__":
    unittest.main()
