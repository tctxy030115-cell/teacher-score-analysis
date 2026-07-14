"""Word 成绩分析报告的构建与导出逻辑。"""

from __future__ import annotations

from datetime import date
from io import BytesIO
import logging
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pandas as pd
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage


LOGGER = logging.getLogger(__name__)
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "score_report_template.docx"
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


class ReportGenerationError(RuntimeError):
    """面向页面展示的报告生成错误。"""


def _format_score(value: object) -> str:
    """按成绩展示习惯格式化数值，避免无意义的小数点。"""
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _format_rate(value: object) -> str:
    return f"{float(value):.1f}%"


def _format_student_list(students: pd.DataFrame, empty_message: str) -> str:
    if students is None or students.empty:
        return empty_message

    return "\n".join(
        f"{row['姓名']}：{_format_score(row['分数'])} 分"
        for _, row in students.iterrows()
    )


def _build_summary_text(analysis_result: dict, selected_class: str, score_col: str, full_score: float) -> str:
    return (
        f"本次{selected_class}的{score_col}分析共覆盖 {analysis_result['student_count']} 名参考学生，"
        f"平均分为 {_format_score(analysis_result['average_score'])} 分，"
        f"最高分为 {_format_score(analysis_result['highest_score'])} 分，"
        f"最低分为 {_format_score(analysis_result['lowest_score'])} 分。"
        f"当前分析列满分为 {_format_score(full_score)} 分，"
        f"及格率为 {_format_rate(analysis_result['pass_rate'])}，"
        f"优秀率为 {_format_rate(analysis_result['excellent_rate'])}。"
    )


def _build_teaching_suggestions(analysis_result: dict) -> str:
    suggestions = ["建议结合本次成绩分布，安排分层练习与阶段性反馈。"]
    if analysis_result.get("fail_count", 0):
        suggestions.append("建议持续关注待提升学生的学习过程，并提供针对性的巩固支持。")
    if analysis_result.get("excellent_count", 0):
        suggestions.append("建议为表现突出的学生提供适度的拓展练习，保持学习积极性。")
    return "\n".join(suggestions)


def build_report_context(
    *,
    analysis_result: dict,
    excellent_df: pd.DataFrame,
    fail_df: pd.DataFrame,
    selected_class: str,
    score_col: str,
    full_score: float,
    school_name: str,
    exam_name: str,
    report_date: str | None = None,
) -> dict:
    """构建报告文字上下文；仅使用页面已经得出的统计和名单。"""
    class_name = str(selected_class).strip() or "全部班级"
    subject_name = str(score_col).strip() or "未填写"
    school_display = str(school_name).strip() or "未填写"
    exam_display = str(exam_name).strip() or "成绩分析"

    return {
        "school_name": school_display,
        "exam_name": exam_display,
        "class_name": class_name,
        "subject_name": subject_name,
        "report_date": report_date or date.today().isoformat(),
        "student_count": str(analysis_result["student_count"]),
        "average_score": f"{float(analysis_result['average_score']):.2f}",
        "highest_score": _format_score(analysis_result["highest_score"]),
        "lowest_score": _format_score(analysis_result["lowest_score"]),
        "pass_rate": _format_rate(analysis_result["pass_rate"]),
        "excellent_rate": _format_rate(analysis_result["excellent_rate"]),
        "summary_text": _build_summary_text(analysis_result, class_name, subject_name, full_score),
        "excellent_students": _format_student_list(excellent_df, "暂无优秀学生"),
        "struggling_students": _format_student_list(fail_df, "暂无待提升学生"),
        "teaching_suggestions": _build_teaching_suggestions(analysis_result),
    }


def safe_report_filename(
    *, school_name: str, class_name: str, subject_name: str, exam_name: str
) -> str:
    """构造 Windows 与 Streamlit 下载都可使用的报告文件名。"""

    def clean_part(value: str, fallback: str) -> str:
        cleaned = _ILLEGAL_FILENAME_CHARS.sub("", str(value)).strip().strip(".")
        return cleaned or fallback

    parts = [
        clean_part(school_name, "未填写"),
        clean_part(class_name, "全部班级"),
        clean_part(subject_name, "未填写"),
        clean_part(exam_name, "成绩分析"),
        "成绩分析报告",
    ]
    return "_".join(parts) + ".docx"


def _export_chart_images(distribution_figure: object, level_figure: object, output_dir: Path) -> tuple[Path, Path]:
    """将页面已有的图表导出为临时 PNG，不在项目目录写入文件。"""
    distribution_path = output_dir / "distribution.png"
    level_path = output_dir / "level.png"
    try:
        distribution_figure.write_image(distribution_path, format="png", width=1200, height=650, scale=2)
        level_figure.write_image(level_path, format="png", width=1000, height=650, scale=2)
    except Exception as exc:
        LOGGER.exception("Word report chart export failed: %s", exc)
        raise ReportGenerationError("Word 报告图表生成失败，请稍后重试或联系管理员。") from exc
    return distribution_path, level_path


def _ensure_no_unrendered_placeholders(report_bytes: bytes) -> None:
    with ZipFile(BytesIO(report_bytes)) as archive:
        xml_parts = [
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ]
    if any(b"{{" in content or b"}}" in content for content in xml_parts):
        LOGGER.error("Word report rendering left template placeholders")
        raise ReportGenerationError("Word 报告模板存在未替换内容，请联系管理员。")


def build_score_report_bytes(
    *,
    analysis_result: dict,
    excellent_df: pd.DataFrame,
    fail_df: pd.DataFrame,
    distribution_figure: object,
    level_figure: object,
    selected_class: str,
    score_col: str,
    full_score: float,
    school_name: str,
    exam_name: str,
    report_date: str | None = None,
    template_path: Path | None = None,
) -> bytes:
    """依次构建文字、导出图表、渲染并返回 Word 文件字节。"""
    template_file = Path(template_path) if template_path is not None else DEFAULT_TEMPLATE_PATH
    if not template_file.is_file():
        raise ReportGenerationError("Word 报告模板不存在，请联系管理员检查模板文件。")

    context = build_report_context(
        analysis_result=analysis_result,
        excellent_df=excellent_df,
        fail_df=fail_df,
        selected_class=selected_class,
        score_col=score_col,
        full_score=full_score,
        school_name=school_name,
        exam_name=exam_name,
        report_date=report_date,
    )

    with TemporaryDirectory(prefix="grade-report-") as temporary_dir:
        distribution_path, level_path = _export_chart_images(
            distribution_figure, level_figure, Path(temporary_dir)
        )
        try:
            template = DocxTemplate(template_file)
            # 165 mm is within the existing A4 template's 1.25-inch side margins.
            context["distribution_chart"] = InlineImage(template, str(distribution_path), width=Mm(165))
            context["level_chart"] = InlineImage(template, str(level_path), width=Mm(165))
            template.render(context, autoescape=True)
            output = BytesIO()
            template.save(output)
            report_bytes = output.getvalue()
            _ensure_no_unrendered_placeholders(report_bytes)
            return report_bytes
        except ReportGenerationError:
            raise
        except Exception as exc:
            LOGGER.exception("Word report rendering failed: %s", exc)
            raise ReportGenerationError("Word 报告生成失败，请稍后重试或联系管理员。") from exc
