import unittest
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

    def test_sidebar_matches_single_page_product_structure(self):
        self.require_ui_components()
        with patch("ui_components.st.sidebar.markdown") as markdown:
            ui_components.render_sidebar()

        rendered = "\n".join(call.args[0] for call in markdown.call_args_list)
        for label in (
            "数据导入",
            "基础统计",
            "成绩分布",
            "学科分析",
            "优秀名单",
            "待提升名单",
            "导出中心",
            "一线教师自用工具 · 持续更新中",
        ):
            self.assertIn(label, rendered)
        self.assertNotIn("Word 报告</a>", rendered)

    def test_figure_style_changes_only_presentation(self):
        self.require_ui_components()
        figure = go.Figure(go.Bar(x=["及格", "优秀"], y=[12, 8]))

        returned = ui_components.style_dashboard_figure(figure, height=390)

        self.assertIs(returned, figure)
        self.assertEqual(list(figure.data[0].y), [12, 8])
        self.assertEqual(figure.layout.paper_bgcolor, "rgba(0,0,0,0)")
        self.assertEqual(figure.layout.plot_bgcolor, "rgba(0,0,0,0)")
        self.assertEqual(figure.layout.height, 390)
        self.assertGreaterEqual(figure.layout.margin.r, 20)


if __name__ == "__main__":
    unittest.main()
