import sys
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = ModuleType("streamlit")

import ui_home


class UiHomeTest(unittest.TestCase):
    def test_home_renders_new_exam_entry_and_empty_recent_analysis(self):
        streamlit = MagicMock()
        on_task_select = MagicMock()

        with patch.object(ui_home, "st", streamlit):
            ui_home.render_home_page(on_task_select=on_task_select)

        rendered_html = "\n".join(
            call.args[0] for call in streamlit.markdown.call_args_list
        )
        self.assertIn("教师成绩分析助手", rendered_html)
        self.assertIn("上传一次考试成绩，自动生成班级、学科和学生分析。", rendered_html)
        self.assertIn("📥 新增考试", rendered_html)
        self.assertIn("最近分析", rendered_html)
        self.assertIn("暂无考试记录", rendered_html)
        self.assertIn("上传一次成绩后，这里会显示你的分析记录。", rendered_html)

        self.assertEqual(streamlit.button.call_count, 1)
        button_call = streamlit.button.call_args
        self.assertEqual(button_call.args[0], "开始导入")
        self.assertEqual(button_call.kwargs["args"], ("single_class",))

    def test_home_does_not_expose_analysis_features_as_top_level_routes(self):
        streamlit = MagicMock()

        with patch.object(ui_home, "st", streamlit):
            ui_home.render_home_page(on_task_select=MagicMock())

        rendered_html = "\n".join(
            call.args[0] for call in streamlit.markdown.call_args_list
        )
        for old_entry in ("班级比较", "两次考试变化", "生成教学报告"):
            self.assertNotIn(old_entry, rendered_html)

    def test_home_can_return_to_current_session_exam(self):
        streamlit = MagicMock()

        with patch.object(ui_home, "st", streamlit):
            ui_home.render_home_page(
                on_task_select=MagicMock(),
                current_exam_name="2026期中考试",
            )

        rendered_html = "\n".join(
            call.args[0] for call in streamlit.markdown.call_args_list
        )
        self.assertIn("2026期中考试", rendered_html)
        self.assertNotIn("暂无考试记录", rendered_html)
        calls = {call.args[0]: call.kwargs for call in streamlit.button.call_args_list}
        self.assertEqual(calls["返回分析"]["args"], ("analysis_center",))

    def test_app_stops_home_before_existing_upload_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        home_gate = source.index('if analysis_mode == "home":')
        workflow_mapping = source.index("workflow_mode =")
        upload_workflow = source.index('render_anchor("data-import")')

        self.assertLess(home_gate, upload_workflow)
        home_block = source[home_gate:workflow_mapping]
        self.assertIn("render_home_page", home_block)
        self.assertIn("st.stop()", home_block)
        self.assertNotIn("file_uploader", home_block)

    def test_existing_business_modules_are_not_replaced_by_home_ui(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn("build_score_report_bytes(", source)
        self.assertIn("build_class_comparison(", source)
        self.assertNotIn("from comparison_logic import", source)


if __name__ == "__main__":
    unittest.main()
