import unittest
from pathlib import Path
from unittest.mock import patch

import plotly.graph_objects as go

try:
    import ui_components
except ImportError:
    ui_components = None


class UiComponentsTest(unittest.TestCase):
    def require_ui_components(self):
        self.assertIsNotNone(ui_components, "缺少 ui_components 模块")

    def test_required_ui_helpers_are_available(self):
        self.require_ui_components()
        for helper_name in (
            "inject_global_styles",
            "render_current_context",
            "render_analysis_summary",
            "render_sidebar",
            "render_page_header",
            "render_section_header",
            "render_metric_grid",
            "render_anchor",
            "style_dashboard_figure",
        ):
            self.assertTrue(hasattr(ui_components, helper_name), helper_name)

    def test_global_styles_include_dashboard_sidebar_and_responsive_metric_grid(self):
        self.require_ui_components()
        with patch("ui_components.st.markdown") as markdown:
            ui_components.inject_global_styles()

        html = markdown.call_args.args[0]
        self.assertIn("#F4F7FB", html)
        self.assertIn('section[data-testid="stSidebar"]', html)
        self.assertIn('[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]', html)
        self.assertNotIn('stVerticalBlockBorderWrapper', html)
        self.assertIn("grid-template-columns: repeat(4", html)
        self.assertIn("@media (max-width: 720px)", html)

    def test_metric_grid_uses_existing_analysis_values_and_formats_them(self):
        self.require_ui_components()
        result = {
            "student_count": 20,
            "average_score": 67.2,
            "highest_score": 96,
            "lowest_score": 28,
            "excellent_count": 1,
            "fail_count": 11,
            "pass_rate": 45,
            "excellent_rate": 5,
        }
        with patch("ui_components.st.markdown") as markdown:
            ui_components.render_metric_grid(result)

        html = markdown.call_args.args[0]
        for expected in ("20", "67.20", "96", "28", "1", "11", "45.0%", "5.0%"):
            self.assertIn(expected, html)
        self.assertIn("metric-grid", html)
        self.assertNotIn("\n", html)

    def test_section_header_html_does_not_break_into_markdown_code_blocks(self):
        self.require_ui_components()
        with patch("ui_components.st.markdown") as markdown:
            ui_components.render_section_header("表头设置", "表")

        html = markdown.call_args.args[0]
        self.assertNotIn("\n", html)
        self.assertTrue(html.strip().endswith("</div>"))

    def test_sidebar_renders_mode_switches_with_stable_unique_keys(self):
        self.require_ui_components()
        on_mode_change = unittest.mock.Mock()
        with (
            patch("ui_components.st.sidebar.markdown") as markdown,
            patch("ui_components.st.sidebar.button") as button,
        ):
            ui_components.render_sidebar(
                analysis_mode="class_comparison",
                on_mode_change=on_mode_change,
            )

        rendered = "\n".join(call.args[0] for call in markdown.call_args_list)
        self.assertIn("分析模式", rendered)
        self.assertIn("一线教师自用工具 · 持续更新中", rendered)

        calls_by_label = {call.args[0]: call.kwargs for call in button.call_args_list}
        self.assertEqual(
            set(calls_by_label),
            {"单班成绩分析", "多班级对比", "两次考试对比（即将上线）"},
        )
        keys = [kwargs["key"] for kwargs in calls_by_label.values()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(
            calls_by_label["单班成绩分析"]["key"],
            "analysis_mode_single_class",
        )
        self.assertEqual(
            calls_by_label["多班级对比"]["key"],
            "analysis_mode_class_comparison",
        )
        self.assertEqual(calls_by_label["多班级对比"]["type"], "primary")
        self.assertEqual(calls_by_label["单班成绩分析"]["type"], "secondary")
        self.assertTrue(calls_by_label["两次考试对比（即将上线）"]["disabled"])
        self.assertIs(
            calls_by_label["多班级对比"]["on_click"],
            on_mode_change,
        )
        self.assertEqual(
            calls_by_label["多班级对比"]["args"],
            ("class_comparison",),
        )

    def test_sidebar_highlights_single_class_mode(self):
        self.require_ui_components()
        with (
            patch("ui_components.st.sidebar.markdown"),
            patch("ui_components.st.sidebar.button") as button,
        ):
            ui_components.render_sidebar(
                analysis_mode="single_class",
                on_mode_change=unittest.mock.Mock(),
            )

        calls_by_label = {call.args[0]: call.kwargs for call in button.call_args_list}
        self.assertEqual(calls_by_label["单班成绩分析"]["type"], "primary")
        self.assertEqual(calls_by_label["多班级对比"]["type"], "secondary")

    def test_sidebar_renders_single_class_navigation_without_form_controls(self):
        self.require_ui_components()
        context_container = object()
        with (
            patch("ui_components.st.sidebar.markdown") as markdown,
            patch("ui_components.st.sidebar.button"),
            patch("ui_components.st.sidebar.selectbox") as selectbox,
            patch("ui_components.st.sidebar.number_input") as number_input,
            patch(
                "ui_components.st.sidebar.container",
                return_value=context_container,
            ) as container,
        ):
            returned_container = ui_components.render_sidebar(
                analysis_mode="single_class",
                on_mode_change=unittest.mock.Mock(),
            )

        rendered = "\n".join(call.args[0] for call in markdown.call_args_list)
        for label, anchor in (
            ("核心统计", "section-overview"),
            ("成绩分布与等级占比", "section-distribution"),
            ("各科平均分", "section-subjects"),
            ("完整成绩明细", "section-details"),
            ("优秀学生", "section-excellent"),
            ("待提升学生", "section-improvement"),
            ("报告导出", "section-export"),
        ):
            self.assertIn(label, rendered)
            self.assertIn(f'href="#{anchor}"', rendered)
        self.assertNotIn("section-class-comparison", rendered)
        self.assertEqual(container.call_count, 1)
        self.assertIs(returned_container, context_container)
        selectbox.assert_not_called()
        number_input.assert_not_called()

    def test_sidebar_renders_class_comparison_navigation_with_semantic_anchors(self):
        self.require_ui_components()
        with (
            patch("ui_components.st.sidebar.markdown") as markdown,
            patch("ui_components.st.sidebar.button"),
            patch("ui_components.st.sidebar.container"),
        ):
            ui_components.render_sidebar(
                analysis_mode="class_comparison",
                on_mode_change=unittest.mock.Mock(),
            )

        rendered = "\n".join(call.args[0] for call in markdown.call_args_list)
        for label, anchor in (
            ("班级横向对比", "section-class-comparison"),
            ("平均得分率", "section-average-rate"),
            ("及格率对比", "section-pass-rate"),
            ("优秀率对比", "section-excellent-rate"),
            ("等级结构", "section-level-structure"),
            ("自动结论", "section-conclusion"),
        ):
            self.assertIn(label, rendered)
            self.assertIn(f'href="#{anchor}"', rendered)
        self.assertNotIn("section-overview", rendered)

    def test_current_context_is_a_single_weak_line(self):
        self.require_ui_components()
        with patch("ui_components.st.markdown") as markdown:
            ui_components.render_current_context("2501 · 数学")

        html = markdown.call_args.args[0]
        self.assertIn("当前：2501 · 数学", html)
        self.assertIn("sidebar-current-context", html)
        self.assertNotIn("工作表", html)
        self.assertNotIn("及格线", html)

    def test_sidebar_links_have_matching_semantic_anchors_in_app(self):
        source = Path("app.py").read_text(encoding="utf-8")
        for anchor in (
            "section-overview",
            "section-distribution",
            "section-subjects",
            "section-details",
            "section-excellent",
            "section-improvement",
            "section-export",
            "section-class-comparison",
            "section-average-rate",
            "section-pass-rate",
            "section-excellent-rate",
            "section-level-structure",
            "section-conclusion",
        ):
            self.assertIn(f'render_anchor("{anchor}")', source)

    def test_analysis_settings_controls_are_not_rendered_in_sidebar_container(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertNotIn("sidebar_config", source)
        self.assertIn('render_section_header("分析设置"', source)
        for key in (
            'key="analysis_sheet"',
            'key="analysis_score_column"',
            'key="analysis_pass_percent"',
            'key="analysis_excellent_percent"',
            'key="analysis_single_class"',
        ):
            self.assertIn(key, source)

    def test_filtered_single_class_result_still_feeds_excel_and_word_exports(self):
        source = Path("app.py").read_text(encoding="utf-8")

        filter_position = source.index("analysis_df = filter_dataframe_by_class")
        analysis_position = source.index("analysis_result = analyze_scores")
        self.assertLess(filter_position, analysis_position)
        self.assertIn("export_score_result_to_bytes(analysis_result)", source)
        self.assertIn("analysis_result=analysis_result", source)
        self.assertIn("selected_class=selected_class", source)

    def test_all_students_scope_uses_range_wording_in_core_statistics(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn('selected_class == "全部学生"', source)
        self.assertIn('f"当前范围：全部学生 · 科目：{score_col}"', source)
        self.assertIn('f"当前班级：{selected_class} · 科目：{score_col}"', source)

    def test_missing_class_column_keeps_hidden_single_class_state_as_all_students(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn(
            'st.session_state["analysis_single_class"] = "全部学生"',
            source,
        )

    def test_figure_style_changes_only_presentation(self):
        self.require_ui_components()
        figure = go.Figure(go.Bar(x=["及格", "优秀"], y=[12, 8]))

        returned = ui_components.style_dashboard_figure(figure, height=390)

        self.assertIs(returned, figure)
        self.assertEqual(list(figure.data[0].y), [12, 8])
        self.assertEqual(figure.layout.paper_bgcolor, "rgba(0,0,0,0)")
        self.assertEqual(figure.layout.plot_bgcolor, "rgba(0,0,0,0)")
        self.assertEqual(figure.layout.height, 390)
        self.assertEqual(figure.layout.margin.t, 62)
        self.assertGreaterEqual(figure.layout.margin.r, 20)

    def test_figure_style_preserves_larger_existing_top_margin(self):
        self.require_ui_components()
        figure = go.Figure(go.Bar(x=["1班"], y=[100]))
        figure.update_layout(margin={"t": 128})

        ui_components.style_dashboard_figure(figure, height=420)

        self.assertEqual(figure.layout.margin.t, 128)

    def test_figure_style_can_preserve_multi_trace_colors(self):
        self.require_ui_components()
        figure = go.Figure(
            [
                go.Bar(name="及格率", x=["1班"], y=[80], marker_color="#123456"),
                go.Bar(name="优秀率", x=["1班"], y=[30], marker_color="#654321"),
            ]
        )

        ui_components.style_dashboard_figure(
            figure,
            height=420,
            preserve_trace_colors=True,
        )

        self.assertEqual(figure.data[0].marker.color, "#123456")
        self.assertEqual(figure.data[1].marker.color, "#654321")

    def test_figure_style_default_still_applies_single_chart_colors(self):
        self.require_ui_components()
        figure = go.Figure(go.Bar(x=["及格"], y=[12], marker_color="#123456"))

        ui_components.style_dashboard_figure(figure, height=390)

        self.assertEqual(figure.data[0].marker.color, "#4F8DE8")


if __name__ == "__main__":
    unittest.main()
