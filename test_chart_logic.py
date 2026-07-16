import unittest

import pandas as pd

import chart_logic
from grade_logic import SCORE_COLUMN_ALIASES, find_first_matching_column
from chart_logic import (
    build_distribution_figure,
    build_level_donut_figure,
    build_subject_average_figure,
    calculate_score_distribution,
    calculate_subject_averages,
    clean_score_series,
)


class ChartLogicTest(unittest.TestCase):
    def test_subject_averages_recognize_suffixed_subjects_but_exclude_total_and_descriptions(self):
        dataframe = pd.DataFrame(
            {
                "姓名": ["甲", "乙"],
                "语文分数": [100, 80],
                "数学成绩": [120, 100],
                "英语得分": [110, 90],
                "总分分数": [330, 270],
                "班级分数线": [300, 300],
                "年级平均分": [305, 305],
            }
        )

        result = calculate_subject_averages(dataframe)

        self.assertEqual(result["科目"].tolist(), ["语文分数", "数学成绩", "英语得分"])
        self.assertEqual(result["平均分"].tolist(), [90.0, 110.0, 100.0])
        self.assertEqual(result["有效人数"].tolist(), [2, 2, 2])

    def test_current_column_full_score_filters_math_but_keeps_total_scores(self):
        math_scores = clean_score_series(pd.Series([119, 120, 121]), full_score=120)
        total_scores = clean_score_series(pd.Series([500, 600, 700, 801]), full_score=800)

        self.assertEqual(math_scores.tolist(), [119.0, 120.0])
        self.assertEqual(total_scores.tolist(), [500.0, 600.0, 700.0])

    def test_invalid_score_reasons_are_exclusive_and_distinguishable(self):
        self.assertTrue(hasattr(chart_logic, "classify_score_rows"), "缺少 classify_score_rows")
        self.assertTrue(hasattr(chart_logic, "count_invalid_reasons"), "缺少 count_invalid_reasons")

        classified = chart_logic.classify_score_rows(
            pd.Series([None, "乙", "丙", "丁", "戊", "己"]),
            pd.Series([999, None, "缺考", -1, 121, 120]),
            full_score=120,
        )
        counts = chart_logic.count_invalid_reasons(classified)

        self.assertEqual(
            counts,
            {
                "姓名为空": 1,
                "分数为空或非数字": 2,
                "分数小于 0": 1,
                "分数高于当前满分": 1,
            },
        )
        self.assertEqual(int(classified["无效原因"].notna().sum()), 5)
        self.assertEqual(classified.loc[classified["无效原因"].isna(), "分数"].tolist(), [120.0])

    def test_invalid_data_warning_lists_reasons_and_highlights_full_score(self):
        self.assertTrue(hasattr(chart_logic, "build_invalid_data_warning"), "缺少 build_invalid_data_warning")

        warning = chart_logic.build_invalid_data_warning(
            {
                "姓名为空": 1,
                "分数为空或非数字": 2,
                "分数小于 0": 1,
                "分数高于当前满分": 4,
            },
            full_score=120,
        )

        self.assertIn("已跳过 8 行无效数据", warning)
        self.assertIn("姓名为空：1 行", warning)
        self.assertIn("分数为空或非数字：2 行", warning)
        self.assertIn("分数小于 0：1 行", warning)
        self.assertIn("分数高于当前满分 120 分：4 行", warning)
        self.assertIn("请检查“当前分析列满分”设置", warning)
        self.assertIn("原始 Excel 未被修改", warning)
        self.assertIsNone(chart_logic.build_invalid_data_warning({}, full_score=100))

    def test_subject_averages_do_not_use_current_column_full_score_as_upper_bound(self):
        dataframe = pd.DataFrame(
            {
                "姓名": ["甲", "乙", "丙"],
                "数学": [120, 130, -1],
                "物理": [100, "缺考", 90],
                "总分": [700, 650, 600],
            }
        )

        result = calculate_subject_averages(dataframe, full_score=100)

        self.assertEqual(result["科目"].tolist(), ["数学", "物理"])
        self.assertEqual(result["平均分"].tolist(), [125.0, 95.0])
        self.assertEqual(result["有效人数"].tolist(), [2, 2])
        self.assertNotIn("总分", result["科目"].tolist())

    def test_statistics_detail_and_current_score_charts_share_valid_rows(self):
        self.assertTrue(hasattr(chart_logic, "classify_score_rows"), "缺少 classify_score_rows")
        from grade_logic import analyze_scores

        classified = chart_logic.classify_score_rows(
            pd.Series(["甲", "乙", "丙", "丁", "戊"]),
            pd.Series([500, 600, 700, 801, "缺考"]),
            full_score=800,
        )
        valid_scores = classified[classified["无效原因"].isna()].copy()
        analysis_result = analyze_scores(dict(zip(valid_scores["姓名"], valid_scores["分数"])), full_score=800)
        distribution = calculate_score_distribution(valid_scores["分数"], full_score=800)

        detail_count = len(analysis_result["score_details"])
        distribution_count = int(distribution["人数"].sum())
        donut_count = int(distribution.attrs["有效人数"])
        self.assertEqual(analysis_result["student_count"], len(valid_scores))
        self.assertEqual(detail_count, len(valid_scores))
        self.assertEqual(distribution_count, len(valid_scores))
        self.assertEqual(donut_count, len(valid_scores))

    def test_subject_alias_expansion_preserves_existing_default_match_priority(self):
        matched = find_first_matching_column(["姓名", "语文", "数学"], SCORE_COLUMN_ALIASES)

        self.assertEqual(matched, "数学")

    def test_clean_score_series_filters_invalid_values_without_mutating_source(self):
        source = pd.Series([59, None, "缺考", -1, 100, 101, "80"])

        result = clean_score_series(source, full_score=100)

        self.assertEqual(result.tolist(), [59.0, 100.0, 80.0])
        self.assertEqual(source.tolist(), [59, None, "缺考", -1, 100, 101, "80"])

    def test_distribution_uses_default_boundaries_and_higher_bucket_on_edges(self):
        scores = pd.Series([59, 60, 69, 70, 79, 80, 89, 90, 100])

        result = calculate_score_distribution(scores, full_score=100, excellent_percent=90)

        self.assertEqual(result["档位"].tolist(), ["待提升", "及格", "中等", "良好", "优秀"])
        self.assertEqual(result["区间"].tolist(), ["0–59", "60–69", "70–79", "80–89", "90–100"])
        self.assertEqual(result["人数"].tolist(), [1, 2, 2, 2, 2])
        self.assertAlmostEqual(result["占比"].sum(), 100.0)
        self.assertEqual(result.attrs["有效人数"], 9)
        self.assertAlmostEqual(result.attrs["平均分"], 77.3333333333)

    def test_distribution_uses_clear_non_overlapping_boundaries_for_120_points(self):
        scores = pd.Series([71.9, 72, 83.9, 84, 95.9, 96, 107.9, 108, 120, 121])

        result = calculate_score_distribution(scores, full_score=120, excellent_percent=90)

        self.assertEqual(
            result["区间"].tolist(),
            ["[0, 72)", "[72, 84)", "[84, 96)", "[96, 108)", "[108, 120]"],
        )
        self.assertEqual(result["人数"].tolist(), [1, 2, 2, 2, 2])
        self.assertEqual(result.attrs["有效人数"], 9)

    def test_distribution_respects_custom_excellent_line_used_by_current_statistics(self):
        result = calculate_score_distribution(
            pd.Series([84, 85, 90]),
            full_score=100,
            excellent_percent=85,
        )

        counts = dict(zip(result["档位"], result["人数"]))
        self.assertEqual(counts["良好"], 1)
        self.assertEqual(counts["优秀"], 2)
        self.assertEqual(result["区间"].tolist()[-2:], ["80–84", "85–100"])

    def test_empty_distribution_returns_stable_empty_counts(self):
        result = calculate_score_distribution(
            pd.Series([None, "缺考", -1, 101]),
            full_score=100,
        )

        self.assertEqual(result["人数"].tolist(), [0, 0, 0, 0, 0])
        self.assertEqual(result["占比"].tolist(), [0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(result.attrs["有效人数"], 0)
        self.assertIsNone(result.attrs["平均分"])

    def test_subject_averages_only_include_two_or_more_valid_regular_subjects(self):
        dataframe = pd.DataFrame(
            {
                "姓名": ["甲", "乙", "丙"],
                "班级": ["1班", "1班", "1班"],
                "考号": [1, 2, 3],
                "语文": [90, "缺考", 60],
                "数学": [100, 80, 120],
                "总分": [190, 80, 180],
                "分数": [90, 80, 70],
                "排名": [1, 2, 3],
            }
        )

        result = calculate_subject_averages(dataframe, full_score=100)

        self.assertEqual(result["科目"].tolist(), ["语文", "数学"])
        self.assertEqual(result["平均分"].tolist(), [75.0, 100.0])
        self.assertEqual(result["有效人数"].tolist(), [2, 3])
        self.assertNotIn("总分", result["科目"].tolist())
        self.assertNotIn("分数", result["科目"].tolist())

    def test_single_subject_or_empty_subject_does_not_create_comparison_data(self):
        dataframe = pd.DataFrame(
            {
                "姓名": ["甲", "乙"],
                "语文": [90, 80],
                "数学": [None, "缺考"],
                "总分": [90, 80],
            }
        )

        result = calculate_subject_averages(dataframe, full_score=100)

        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), ["科目", "平均分", "有效人数"])

    def test_figure_builders_create_expected_plotly_traces(self):
        distribution = calculate_score_distribution(
            pd.Series([59, 60, 70, 80, 90]),
            full_score=100,
        )
        subject_averages = pd.DataFrame(
            {"科目": ["语文", "数学"], "平均分": [82.5, 88.0], "有效人数": [2, 2]}
        )

        distribution_figure = build_distribution_figure(distribution)
        donut_figure = build_level_donut_figure(distribution)
        subject_figure = build_subject_average_figure(subject_averages)

        self.assertEqual(distribution_figure.data[0].type, "bar")
        self.assertEqual(distribution_figure.data[0].texttemplate, "%{y}")
        self.assertEqual(donut_figure.data[0].type, "pie")
        self.assertAlmostEqual(donut_figure.data[0].hole, 0.58)
        self.assertEqual(subject_figure.data[0].texttemplate, "%{y:.1f}")

    def test_all_figure_text_uses_cross_platform_chinese_font_fallback(self):
        distribution = calculate_score_distribution(
            pd.Series([59, 60, 70, 80, 90]),
            full_score=100,
        )
        subject_averages = pd.DataFrame(
            {"科目": ["语文", "数学"], "平均分": [82.5, 88.0], "有效人数": [2, 2]}
        )
        figures = (
            build_distribution_figure(distribution),
            build_level_donut_figure(distribution),
            build_subject_average_figure(subject_averages),
        )

        for figure in figures:
            font_families = [
                figure.layout.font.family,
                figure.layout.title.font.family,
                figure.layout.legend.font.family,
                *(trace.textfont.family for trace in figure.data),
                *(annotation.font.family for annotation in figure.layout.annotations),
            ]
            if figure.data[0].type == "bar":
                font_families.extend(
                    [
                        figure.layout.xaxis.tickfont.family,
                        figure.layout.xaxis.title.font.family,
                        figure.layout.yaxis.tickfont.family,
                        figure.layout.yaxis.title.font.family,
                    ]
                )

            for family in font_families:
                self.assertIsNotNone(family)
                self.assertIn("Noto Sans CJK SC", family)
                self.assertNotEqual(family, "Microsoft YaHei")


if __name__ == "__main__":
    unittest.main()
