from io import BytesIO
from pathlib import Path
import unittest
from zipfile import ZipFile

import pandas as pd
import plotly.graph_objects as go
from docx import Document

try:
    import report_logic
except ImportError:
    report_logic = None


class ReportLogicTest(unittest.TestCase):
    def setUp(self):
        self.analysis_result = {
            "student_count": 3,
            "average_score": 88.5,
            "highest_score": 100.0,
            "lowest_score": 72.0,
            "pass_rate": 66.6666,
            "excellent_rate": 33.3333,
        }
        self.excellent_df = pd.DataFrame([["张三&甲", 100]], columns=["姓名", "分数"])
        self.fail_df = pd.DataFrame([["李<四", 58]], columns=["姓名", "分数"])
        self.distribution_figure = go.Figure(go.Bar(x=["及格", "优秀"], y=[2, 1]))
        self.level_figure = go.Figure(go.Pie(labels=["及格", "优秀"], values=[2, 1]))

    def require_report_logic(self):
        self.assertIsNotNone(report_logic, "缺少 report_logic 模块")

    def test_build_report_context_formats_current_web_values_and_empty_inputs(self):
        self.require_report_logic()

        context = report_logic.build_report_context(
            analysis_result=self.analysis_result,
            excellent_df=self.excellent_df,
            fail_df=self.fail_df,
            selected_class="2401",
            score_col="数学分数",
            full_score=120,
            school_name="",
            exam_name="",
            report_date="2026-07-14",
        )

        self.assertEqual(context["school_name"], "未填写")
        self.assertEqual(context["exam_name"], "成绩分析")
        self.assertEqual(context["class_name"], "2401")
        self.assertEqual(context["subject_name"], "数学分数")
        self.assertEqual(context["student_count"], "3")
        self.assertEqual(context["average_score"], "88.50")
        self.assertEqual(context["highest_score"], "100")
        self.assertEqual(context["lowest_score"], "72")
        self.assertEqual(context["pass_rate"], "66.7%")
        self.assertEqual(context["excellent_rate"], "33.3%")
        self.assertIn("张三&甲：100 分", context["excellent_students"])
        self.assertIn("李<四：58 分", context["struggling_students"])
        self.assertNotIn("成绩较差", context["summary_text"] + context["teaching_suggestions"])

    def test_build_report_context_uses_empty_list_fallbacks(self):
        self.require_report_logic()

        context = report_logic.build_report_context(
            analysis_result=self.analysis_result,
            excellent_df=pd.DataFrame(columns=["姓名", "分数"]),
            fail_df=pd.DataFrame(columns=["姓名", "分数"]),
            selected_class="全部班级",
            score_col="总成绩分数",
            full_score=800,
            school_name="学校",
            exam_name="考试",
            report_date="2026-07-14",
        )

        self.assertEqual(context["excellent_students"], "暂无优秀学生")
        self.assertEqual(context["struggling_students"], "暂无待提升学生")

    def test_safe_report_filename_removes_windows_illegal_characters(self):
        self.require_report_logic()

        filename = report_logic.safe_report_filename(
            school_name='学/校:*?',
            class_name='2401|班',
            subject_name='数学<分数>',
            exam_name='期"末\\考',
        )

        self.assertEqual(filename, "学校_2401班_数学分数_期末考_成绩分析报告.docx")

    def test_missing_template_raises_friendly_error(self):
        self.require_report_logic()

        with self.assertRaisesRegex(report_logic.ReportGenerationError, "Word 报告模板不存在"):
            report_logic.build_score_report_bytes(
                analysis_result=self.analysis_result,
                excellent_df=self.excellent_df,
                fail_df=self.fail_df,
                distribution_figure=self.distribution_figure,
                level_figure=self.level_figure,
                selected_class="2401",
                score_col="数学",
                full_score=120,
                school_name="学校",
                exam_name="考试",
                template_path=Path("missing-template.docx"),
            )

    def test_chart_export_failure_does_not_return_partial_report(self):
        self.require_report_logic()

        class FailingFigure:
            def write_image(self, *_args, **_kwargs):
                raise RuntimeError("browser unavailable")

        with self.assertRaisesRegex(report_logic.ReportGenerationError, "Word 报告图表生成失败"):
            report_logic.build_score_report_bytes(
                analysis_result=self.analysis_result,
                excellent_df=self.excellent_df,
                fail_df=self.fail_df,
                distribution_figure=FailingFigure(),
                level_figure=FailingFigure(),
                selected_class="2401",
                score_col="数学",
                full_score=120,
                school_name="学校",
                exam_name="考试",
            )

    def test_generated_report_is_valid_docx_with_two_images_and_no_placeholders(self):
        self.require_report_logic()

        report_bytes = report_logic.build_score_report_bytes(
            analysis_result=self.analysis_result,
            excellent_df=self.excellent_df,
            fail_df=self.fail_df,
            distribution_figure=self.distribution_figure,
            level_figure=self.level_figure,
            selected_class="2401",
            score_col="数学",
            full_score=120,
            school_name="示例学校",
            exam_name="期末考试",
            report_date="2026-07-14",
        )

        with ZipFile(BytesIO(report_bytes)) as archive:
            media_names = [name for name in archive.namelist() if name.startswith("word/media/")]
            document_xml = archive.read("word/document.xml").decode("utf-8")
        document = Document(BytesIO(report_bytes))
        rendered_text = "\n".join(paragraph.text for paragraph in document.paragraphs)

        self.assertEqual(len(media_names), 2)
        self.assertNotIn("{{", document_xml)
        self.assertNotIn("}}", document_xml)
        self.assertIn("示例学校", rendered_text)
        self.assertIn("张三&甲", rendered_text)
        self.assertIn("李<四", rendered_text)

    def test_report_generation_leaves_no_project_png_or_docx(self):
        self.require_report_logic()
        project_root = Path(__file__).resolve().parent
        before = {path.name for path in project_root.glob("*.png")} | {
            path.name for path in project_root.glob("*.docx")
        }
        report_logic.build_score_report_bytes(
            analysis_result=self.analysis_result,
            excellent_df=self.excellent_df,
            fail_df=self.fail_df,
            distribution_figure=self.distribution_figure,
            level_figure=self.level_figure,
            selected_class="2401",
            score_col="数学",
            full_score=120,
            school_name="学校",
            exam_name="考试",
        )
        after = {path.name for path in project_root.glob("*.png")} | {
            path.name for path in project_root.glob("*.docx")
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
