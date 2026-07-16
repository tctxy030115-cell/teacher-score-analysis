import unittest

import pandas as pd

from class_comparison_logic import (
    FAIRNESS_NOTICE,
    LEVEL_NAMES,
    build_average_rate_figure,
    build_class_comparison,
    build_comparison_conclusion,
    build_level_structure_figure,
    build_pass_excellent_figure,
    natural_sort_class_names,
)


class ClassComparisonLogicTest(unittest.TestCase):
    @staticmethod
    def build_result(dataframe, classes=None, full_score=100, excellent_percent=90):
        selected = classes or natural_sort_class_names(dataframe["班级"])
        return build_class_comparison(
            dataframe,
            class_column="班级",
            name_column="姓名",
            score_column="成绩",
            selected_classes=selected,
            full_score=full_score,
            excellent_percent=excellent_percent,
        )

    def test_two_classes_calculate_average_and_average_rate(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [80, 100, 60, 80],
            }
        )

        summary = self.build_result(dataframe).summary.set_index("班级")

        self.assertAlmostEqual(summary.loc["1班", "平均分"], 90.0)
        self.assertAlmostEqual(summary.loc["1班", "平均得分率"], 90.0)
        self.assertAlmostEqual(summary.loc["2班", "平均分"], 70.0)
        self.assertAlmostEqual(summary.loc["2班", "平均得分率"], 70.0)

    def test_different_class_sizes_keep_separate_counts(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "1班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, 80, 70, 60],
            }
        )

        summary = self.build_result(dataframe).summary.set_index("班级")

        self.assertEqual(summary.loc["1班", "原始记录数"], 3)
        self.assertEqual(summary.loc["2班", "原始记录数"], 1)
        self.assertEqual(summary.loc["1班", "有效人数"], 3)
        self.assertEqual(summary.loc["2班", "有效人数"], 1)

    def test_duplicate_student_names_are_preserved_as_rows(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["同名", "同名", "同名", "同名"],
                "成绩": [60, 100, 70, 90],
            }
        )

        summary = self.build_result(dataframe).summary.set_index("班级")

        self.assertEqual(summary.loc["1班", "有效人数"], 2)
        self.assertAlmostEqual(summary.loc["1班", "平均分"], 80.0)
        self.assertEqual(summary.loc["2班", "有效人数"], 2)

    def test_absence_and_non_numeric_scores_are_skipped(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊"],
                "成绩": [90, "缺考", "无", 80, None],
            }
        )

        summary = self.build_result(dataframe).summary.set_index("班级")

        self.assertEqual(summary.loc["1班", "有效人数"], 1)
        self.assertEqual(summary.loc["1班", "跳过人数"], 2)
        self.assertEqual(summary.loc["2班", "有效人数"], 1)
        self.assertEqual(summary.loc["2班", "跳过人数"], 1)

    def test_negative_and_above_full_score_values_are_skipped(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊"],
                "成绩": [-1, 101, 100, 50, 102],
            }
        )

        summary = self.build_result(dataframe).summary.set_index("班级")

        self.assertEqual(summary.loc["1班", "有效人数"], 1)
        self.assertEqual(summary.loc["1班", "跳过人数"], 2)
        self.assertEqual(summary.loc["2班", "有效人数"], 1)
        self.assertEqual(summary.loc["2班", "跳过人数"], 1)

    def test_all_invalid_class_is_excluded_with_reason(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [80, 90, "缺考", 101],
            }
        )

        result = self.build_result(dataframe)

        self.assertEqual(result.summary["班级"].tolist(), ["1班"])
        self.assertEqual(result.excluded["班级"].tolist(), ["2班"])
        self.assertEqual(int(result.excluded.iloc[0]["原始记录数"]), 2)
        self.assertEqual(int(result.excluded.iloc[0]["跳过人数"]), 2)
        self.assertIn("无有效成绩", result.excluded.iloc[0]["排除原因"])

    def test_five_level_boundaries_are_consistent(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班"] * 9 + ["2班"],
                "姓名": [f"学生{i}" for i in range(10)],
                "成绩": [59.9, 60, 69.9, 70, 79.9, 80, 89.9, 90, 100, 80],
            }
        )

        result = self.build_result(dataframe)
        levels = result.levels[result.levels["班级"] == "1班"].set_index("等级")

        self.assertEqual(levels["人数"].to_dict(), {"待提升": 1, "及格": 2, "中等": 2, "良好": 2, "优秀": 2})

    def test_100_point_scale_rates(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班"] * 4 + ["2班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊"],
                "成绩": [59, 60, 90, 100, 80],
            }
        )

        row = self.build_result(dataframe).summary.set_index("班级").loc["1班"]

        self.assertAlmostEqual(row["及格率"], 75.0)
        self.assertAlmostEqual(row["优秀率"], 50.0)
        self.assertAlmostEqual(row["待提升率"], 25.0)

    def test_120_point_scale_boundaries(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班"] * 5 + ["2班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊", "己"],
                "成绩": [71.9, 72, 84, 96, 108, 100],
            }
        )

        result = self.build_result(dataframe, full_score=120)
        levels = result.levels[result.levels["班级"] == "1班"].set_index("等级")

        self.assertEqual(levels["人数"].to_dict(), {"待提升": 1, "及格": 1, "中等": 1, "良好": 1, "优秀": 1})

    def test_800_point_total_score_boundaries(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班"] * 5 + ["2班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊", "己"],
                "成绩": [479, 480, 560, 640, 720, 600],
            }
        )

        result = self.build_result(dataframe, full_score=800)
        levels = result.levels[result.levels["班级"] == "1班"].set_index("等级")

        self.assertEqual(levels["人数"].to_dict(), {"待提升": 1, "及格": 1, "中等": 1, "良好": 1, "优秀": 1})

    def test_summary_contains_required_counts_and_rates(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班"] * 5 + ["2班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊", "己"],
                "成绩": [50, 60, 70, 80, 90, 100],
            }
        )

        row = self.build_result(dataframe).summary.set_index("班级").loc["1班"]

        self.assertEqual(row["及格人数"], 4)
        self.assertEqual(row["优秀人数"], 1)
        self.assertEqual(row["待提升人数"], 1)
        self.assertAlmostEqual(row["及格率"], 80.0)
        self.assertAlmostEqual(row["优秀率"], 20.0)
        self.assertAlmostEqual(row["待提升率"], 20.0)

    def test_each_class_level_percentages_sum_to_about_100(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班"] * 3 + ["2班"] * 7,
                "姓名": [f"学生{i}" for i in range(10)],
                "成绩": [50, 70, 90, 55, 65, 75, 85, 95, 88, 77],
            }
        )

        totals = self.build_result(dataframe).levels.groupby("班级")["占比"].sum()

        for total in totals:
            self.assertAlmostEqual(total, 100.0)

    def test_class_names_use_natural_sorting_and_ignore_blanks(self):
        values = pd.Series(["10班", "2班", "1班", 2403.0, 2401, "2402", "", None, "2班"])

        result = natural_sort_class_names(values)

        self.assertEqual(result, ["1班", "2班", "10班", "2401", "2402", "2403"])

    def test_average_rate_ties_are_all_named_in_conclusion(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班", "3班", "3班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊", "己"],
                "成绩": [80, 90, 85, 85, 60, 70],
            }
        )

        conclusion = build_comparison_conclusion(self.build_result(dataframe).summary)

        self.assertIn("1班、2班", conclusion)
        self.assertIn("平均得分率最高", conclusion)

    def test_pass_rate_ties_are_all_named_in_conclusion(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班", "3班", "3班"],
                "姓名": ["甲", "乙", "丙", "丁", "戊", "己"],
                "成绩": [60, 90, 70, 80, 50, 90],
            }
        )

        conclusion = build_comparison_conclusion(self.build_result(dataframe).summary)

        self.assertIn("及格率最高的班级为1班、2班", conclusion)

    def test_conclusion_is_neutral_and_includes_difference_rule(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, 90, 70, 70],
            }
        )

        conclusion = build_comparison_conclusion(self.build_result(dataframe).summary)

        self.assertIn("百分点", conclusion)
        self.assertIn("差异较为明显", conclusion)
        self.assertNotIn("最差", conclusion)
        self.assertNotIn("教学质量", conclusion)
        self.assertNotIn("教师", conclusion)
        self.assertIn("不直接作为教学质量评价依据", FAIRNESS_NOTICE)

    def test_less_than_two_selected_classes_returns_stable_empty_result(self):
        dataframe = pd.DataFrame({"班级": ["1班"], "姓名": ["甲"], "成绩": [90]})

        result = self.build_result(dataframe, classes=["1班"])

        self.assertTrue(result.summary.empty)
        self.assertTrue(result.levels.empty)
        self.assertTrue(result.excluded.empty)
        self.assertFalse(result.is_comparable)

    def test_three_figures_have_expected_trace_structures(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, 80, 70, 60],
            }
        )
        result = self.build_result(dataframe)

        average = build_average_rate_figure(result.summary)
        rates = build_pass_excellent_figure(result.summary)
        levels = build_level_structure_figure(result.levels)

        self.assertEqual(len(average.data), 1)
        self.assertEqual(average.data[0].type, "bar")
        self.assertEqual(len(rates.data), 2)
        self.assertEqual(rates.layout.barmode, "group")
        self.assertEqual(
            [trace.name for trace in levels.data],
            ["优秀", "良好", "中等", "及格", "待提升"],
        )
        self.assertEqual(levels.layout.barmode, "stack")

    def test_level_structure_uses_semantic_colors_and_compact_layout(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, 80, 70, 60],
            }
        )
        result = self.build_result(dataframe)

        figure = build_level_structure_figure(result.levels)

        self.assertEqual(
            {trace.name: trace.marker.color for trace in figure.data},
            {
                "优秀": "#22C55E",
                "良好": "#3B82F6",
                "中等": "#EAB308",
                "及格": "#A855F7",
                "待提升": "#EF4444",
            },
        )
        self.assertEqual(figure.layout.legend.orientation, "h")
        self.assertEqual(figure.layout.legend.traceorder, "normal")
        self.assertGreaterEqual(figure.layout.legend.font.size, 13)
        self.assertEqual(list(figure.layout.yaxis.range), [0, 100])
        self.assertGreaterEqual(figure.layout.bargap, 0.25)
        self.assertEqual(figure.layout.paper_bgcolor, "rgba(0,0,0,0)")
        self.assertEqual(figure.layout.plot_bgcolor, "rgba(0,0,0,0)")

    def test_level_structure_separates_title_and_legend_rows(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, 80, 70, 60],
            }
        )
        result = self.build_result(dataframe)

        figure = build_level_structure_figure(result.levels)

        self.assertEqual(figure.layout.title.yref, "container")
        self.assertEqual(figure.layout.title.y, 0.98)
        self.assertEqual(figure.layout.title.yanchor, "top")
        self.assertTrue(figure.layout.title.automargin)
        self.assertEqual(figure.layout.legend.orientation, "h")
        self.assertEqual(figure.layout.legend.yref, "paper")
        self.assertEqual(figure.layout.legend.y, 1.02)
        self.assertEqual(figure.layout.legend.yanchor, "bottom")
        self.assertGreaterEqual(figure.layout.margin.t, 128)
        self.assertEqual(figure.layout.height, 420)

    def test_level_structure_labels_and_hover_follow_visibility_thresholds(self):
        levels = pd.DataFrame(
            {
                "班级": ["1班"] * 5,
                "等级": ["优秀", "良好", "中等", "及格", "待提升"],
                "人数": [10, 7, 2, 1, 1],
                "占比": [50.0, 35.0, 8.0, 4.0, 3.0],
            }
        )

        figure = build_level_structure_figure(levels)
        traces = {trace.name: trace for trace in figure.data}

        self.assertEqual(list(traces["优秀"].text), ["10人<br>50.0%"])
        self.assertEqual(list(traces["中等"].text), ["2人<br>8.0%"])
        self.assertEqual(list(traces["及格"].text), ["4.0%"])
        self.assertEqual(list(traces["待提升"].text), [""])
        for trace in figure.data:
            self.assertEqual(trace.textposition, "inside")
            self.assertEqual(trace.insidetextanchor, "middle")
            self.assertIn("班级", trace.hovertemplate)
            self.assertIn("人数", trace.hovertemplate)
            self.assertIn("占有效人数比例", trace.hovertemplate)
            self.assertIn("<extra></extra>", trace.hovertemplate)
        self.assertEqual(traces["优秀"].textfont.color, "#0F172A")
        self.assertEqual(traces["良好"].textfont.color, "#FFFFFF")
        self.assertEqual(traces["中等"].textfont.color, "#1F2937")
        self.assertEqual(traces["及格"].textfont.color, "#FFFFFF")
        self.assertEqual(traces["待提升"].textfont.color, "#FFFFFF")

    def test_three_figures_apply_chinese_font_to_all_text(self):
        dataframe = pd.DataFrame(
            {
                "班级": ["1班", "1班", "2班", "2班"],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, 80, 70, 60],
            }
        )
        result = self.build_result(dataframe)
        figures = (
            build_average_rate_figure(result.summary),
            build_pass_excellent_figure(result.summary),
            build_level_structure_figure(result.levels),
        )

        for figure in figures:
            families = [
                figure.layout.font.family,
                figure.layout.title.font.family,
                figure.layout.legend.font.family,
                figure.layout.xaxis.tickfont.family,
                figure.layout.xaxis.title.font.family,
                figure.layout.yaxis.tickfont.family,
                figure.layout.yaxis.title.font.family,
                *(trace.textfont.family for trace in figure.data),
            ]
            for family in families:
                self.assertIn("Noto Sans CJK SC", family)

    def test_building_comparison_does_not_mutate_source_dataframe(self):
        dataframe = pd.DataFrame(
            {
                "班级": [1.0, 1.0, 2.0, 2.0],
                "姓名": ["甲", "乙", "丙", "丁"],
                "成绩": [90, "缺考", 80, 70],
            }
        )
        original = dataframe.copy(deep=True)

        self.build_result(dataframe)

        pd.testing.assert_frame_equal(dataframe, original)


if __name__ == "__main__":
    unittest.main()
