from io import BytesIO
import unittest

import pandas as pd
from openpyxl import load_workbook

from grade_logic import (
    CLASS_COLUMN_ALIASES,
    analyze_scores,
    build_dataframe_from_header,
    clean_column_name,
    create_single_score_template,
    detect_header_row,
    export_score_result_to_bytes,
    find_first_matching_column,
    format_class_value,
    build_class_options,
    get_score_level,
)


class GradeLogicTest(unittest.TestCase):
    def test_analyze_scores_builds_summary_and_lists(self):
        result = analyze_scores({"Alice": 95, "Bob": 82, "Cindy": 76, "Dan": 58})

        self.assertEqual(result["student_count"], 4)
        self.assertEqual(result["highest_score"], 95)
        self.assertEqual(result["lowest_score"], 58)
        self.assertAlmostEqual(result["average_score"], 77.75)
        self.assertAlmostEqual(result["excellent_rate"], 25.0)
        self.assertAlmostEqual(result["pass_rate"], 75.0)
        self.assertEqual(result["excellent_students"], [["Alice", 95]])
        self.assertEqual(result["fail_students"], [["Dan", 58]])
        self.assertEqual(get_score_level(59.9), "不及格")
        self.assertEqual(get_score_level(90), "优秀")

    def test_export_score_result_returns_downloadable_workbook_bytes(self):
        result = analyze_scores({"Alice": 95, "Bob": 58})
        data = export_score_result_to_bytes(result)

        self.assertIsInstance(data, BytesIO)
        workbook = load_workbook(data)
        self.assertEqual(
            workbook.sheetnames,
            ["成绩明细", "基础统计", "优秀学生名单", "不及格学生名单"],
        )
        basic_values = {
            workbook["基础统计"].cell(row=row, column=1).value: workbook["基础统计"].cell(row=row, column=2).value
            for row in range(1, workbook["基础统计"].max_row + 1)
        }
        self.assertEqual(workbook["成绩明细"]["A1"].value, "名次")
        self.assertEqual(basic_values["总人数"], 2)
        self.assertEqual(workbook["优秀学生名单"]["A2"].value, "Alice")
        self.assertEqual(workbook["不及格学生名单"]["A2"].value, "Bob")

    def test_create_single_score_template_returns_styled_example_workbook(self):
        data = create_single_score_template()

        self.assertIsInstance(data, BytesIO)
        workbook = load_workbook(data)
        self.assertEqual(workbook.sheetnames, ["成绩录入"])

        sheet = workbook["成绩录入"]
        self.assertEqual([sheet["A1"].value, sheet["B1"].value], ["姓名", "分数"])
        self.assertEqual(
            [[sheet.cell(row=row, column=1).value, sheet.cell(row=row, column=2).value] for row in range(2, 6)],
            [["张三", 85], ["李四", 72], ["王五", 96], ["赵六", 58]],
        )
        self.assertTrue(sheet["A1"].font.bold)
        self.assertEqual(sheet["A1"].alignment.horizontal, "center")
        self.assertGreaterEqual(sheet.column_dimensions["A"].width, 6)

    def test_clean_column_name_removes_spaces_newlines_and_full_width_spaces(self):
        self.assertEqual(clean_column_name("　姓名 \n"), "姓名")
        self.assertEqual(clean_column_name("学生\r\n姓名"), "学生姓名")
        self.assertEqual(clean_column_name(123), "123")

    def test_find_first_matching_column_supports_score_aliases(self):
        columns = ["学生姓名", "数学"]

        self.assertEqual(find_first_matching_column(columns, ["姓名", "学生姓名"]), "学生姓名")
        self.assertEqual(find_first_matching_column(columns, ["分数", "成绩", "数学"]), "数学")
        self.assertIsNone(find_first_matching_column(columns, ["总分"]))

    def test_detect_header_row_finds_school_report_header_on_second_row(self):
        raw_df = pd.DataFrame(
            [
                ["零陵区实验中学2026年上期成绩汇总", None, None, None, None, None],
                ["班级", "考号", "姓名", "考室", "语文", "数学"],
                ["七1班", "001", "张三", "A01", 108, 117],
                ["七1班", "002", "李四", "A01", 96, 98],
            ]
        )

        self.assertEqual(detect_header_row(raw_df), 1)
        df = build_dataframe_from_header(raw_df, 1)
        self.assertEqual(df.columns.tolist(), ["班级", "考号", "姓名", "考室", "语文", "数学"])
        self.assertEqual(df["数学"].max(), 117)

    def test_analyze_scores_uses_full_score_for_levels_and_rates(self):
        result = analyze_scores({"张三": 117, "李四": 98, "王五": 71}, full_score=120)

        self.assertEqual(result["highest_score"], 117)
        self.assertEqual(result["score_details"][0], ["张三", 117, "优秀"])
        self.assertEqual(result["score_details"][1], ["李四", 98, "良好"])
        self.assertEqual(result["score_details"][2], ["王五", 71, "不及格"])
        self.assertAlmostEqual(result["excellent_rate"], 100 / 3)
        self.assertAlmostEqual(result["pass_rate"], 200 / 3)
        self.assertEqual(get_score_level(108, full_score=120), "优秀")
        self.assertEqual(get_score_level(96, full_score=120), "良好")
        self.assertEqual(get_score_level(72, full_score=120), "及格")

    def test_analyze_scores_uses_custom_excellent_percent(self):
        result = analyze_scores({"张三": 85, "李四": 84, "王五": 59}, excellent_percent=85)

        self.assertEqual(result["excellent_count"], 1)
        self.assertEqual(result["fail_count"], 1)
        self.assertAlmostEqual(result["excellent_rate"], 100 / 3)
        self.assertEqual(result["excellent_students"], [["张三", 85]])
        self.assertEqual(result["fail_students"], [["王五", 59]])
        self.assertEqual(result["score_details"][0], ["张三", 85, "优秀"])
        self.assertEqual(result["excellent_percent"], 85)
        self.assertEqual(result["pass_percent"], 60)

    def test_excellent_percent_below_pass_line_is_clamped_to_sixty(self):
        result = analyze_scores({"张三": 61, "李四": 59}, excellent_percent=50)

        self.assertEqual(result["excellent_percent"], 60)
        self.assertEqual(result["excellent_count"], 1)
        self.assertEqual(result["fail_count"], 1)
        self.assertEqual(result["score_details"][0], ["张三", 61, "优秀"])

    def test_export_score_result_includes_current_scoring_settings(self):
        result = analyze_scores({"张三": 85, "李四": 59}, full_score=100, excellent_percent=85)
        data = export_score_result_to_bytes(result)

        workbook = load_workbook(data)
        basic_sheet = workbook["基础统计"]
        values = {basic_sheet.cell(row=row, column=1).value: basic_sheet.cell(row=row, column=2).value for row in range(1, basic_sheet.max_row + 1)}

        self.assertEqual(values["满分"], 100)
        self.assertEqual(values["优秀线"], "85%")
        self.assertEqual(values["及格线"], "60%")
        self.assertEqual(values["优秀人数"], 1)
        self.assertEqual(values["不及格人数"], 1)

    def test_class_aliases_and_options_support_numeric_and_text_classes(self):
        self.assertIn("班级", CLASS_COLUMN_ALIASES)
        self.assertIn("行政班", CLASS_COLUMN_ALIASES)

        class_values = pd.Series([2401.0, "2402班", 2401, None, " 2403 "])

        self.assertEqual(format_class_value(2401.0), "2401")
        self.assertEqual(format_class_value("2401班"), "2401班")
        self.assertEqual(build_class_options(class_values), ["全部班级", "2401", "2402班", "2403"])

    def test_analyze_scores_and_export_include_current_class_and_subject(self):
        result = analyze_scores(
            {"张三": 117, "李四": 98},
            full_score=120,
            excellent_percent=90,
            current_class="2401",
            current_subject="数学",
        )
        data = export_score_result_to_bytes(result)

        workbook = load_workbook(data)
        basic_sheet = workbook["基础统计"]
        values = {basic_sheet.cell(row=row, column=1).value: basic_sheet.cell(row=row, column=2).value for row in range(1, basic_sheet.max_row + 1)}

        self.assertEqual(result["current_class"], "2401")
        self.assertEqual(result["current_subject"], "数学")
        self.assertEqual(values["当前班级"], "2401")
        self.assertEqual(values["当前分析科目"], "数学")
        self.assertEqual(values["满分"], 120)
        self.assertEqual(values["优秀线"], "90%")
        self.assertEqual(values["及格线"], "60%")


if __name__ == "__main__":
    unittest.main()
