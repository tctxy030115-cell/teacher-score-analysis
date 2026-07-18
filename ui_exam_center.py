"""当前考试分析中心的产品层 UI，不包含成绩计算逻辑。"""

from __future__ import annotations

from collections.abc import MutableMapping
from html import escape
from io import BytesIO
from typing import Any, BinaryIO

import pandas as pd
import streamlit as st

from student_identity import build_student_identity_records


_ANALYSIS_CENTER_SCROLL_KEY = "analysis_center_scroll_pending"


def activate_analysis_center(session_state: MutableMapping[str, Any]) -> None:
    """把当前会话切换到独立考试分析中心状态。"""
    session_state["analysis_mode"] = "analysis_center"
    session_state[_ANALYSIS_CENTER_SCROLL_KEY] = True


def _render_scroll_component(script: str) -> None:
    """通过零高度局部组件执行滚动脚本，避免刷新整个页面。"""
    import streamlit.components.v1 as components

    components.html(script, height=0, scrolling=False)


def render_analysis_center_top(session_state: MutableMapping[str, Any]) -> None:
    """渲染分析中心顶部目标，并仅响应一次首次进入滚动请求。"""
    st.markdown(
        '<span id="analysis-top" class="dashboard-anchor"></span>',
        unsafe_allow_html=True,
    )
    if not session_state.pop(_ANALYSIS_CENTER_SCROLL_KEY, False):
        return

    _render_scroll_component(
        """
        <script>
        (() => {
            const maxAttempts = 8;
            let attempts = 0;

            const scrollToAnalysisTop = () => {
                attempts += 1;
                const target = window.parent.document.getElementById('analysis-top');
                if (target) {
                    target.scrollIntoView({behavior: 'smooth', block: 'start'});
                    return;
                }
                if (attempts < maxAttempts) {
                    window.setTimeout(scrollToAnalysisTop, 80);
                }
            };

            window.requestAnimationFrame(scrollToAnalysisTop);
        })();
        </script>
        """
    )


def cache_current_exam(
    session_state: MutableMapping[str, Any],
    uploaded_file: BinaryIO,
) -> None:
    """缓存当前考试文件；切换文件时清理上一场考试的报告状态。"""
    file_bytes = uploaded_file.getvalue()
    file_name = getattr(uploaded_file, "name", "当前考试.xlsx")
    is_new_exam = (
        session_state.get("current_exam_file_bytes") != file_bytes
        or session_state.get("current_exam_file_name") != file_name
    )
    if is_new_exam:
        session_state.pop("word_report_exam_name", None)
        session_state.pop("current_exam_snapshot", None)
    session_state["current_exam_file_bytes"] = file_bytes
    session_state["current_exam_file_name"] = file_name


def cache_current_exam_snapshot(
    session_state: MutableMapping[str, Any],
    snapshot: dict[str, Any],
) -> None:
    """保存当前考试已经生成的分析结果，供报告中心只读使用。"""
    session_state["current_exam_snapshot"] = snapshot


def restore_current_exam_file(
    session_state: MutableMapping[str, Any],
) -> BytesIO | None:
    """恢复为兼容现有 Excel 解析流程的内存文件。"""
    file_bytes = session_state.get("current_exam_file_bytes")
    if not file_bytes:
        return None
    restored = BytesIO(file_bytes)
    restored.name = session_state.get("current_exam_file_name", "当前考试.xlsx")
    return restored


def count_exam_classes(class_options: list[str], *, has_class_column: bool) -> int:
    """统计真实班级数，不把分析范围“全部学生”计作班级。"""
    if not has_class_column:
        return 1
    return sum(option != "全部学生" for option in class_options)


def count_exam_students(
    dataframe: pd.DataFrame,
    *,
    name_column: str,
    class_column: str | None,
    student_id_column: str | None = None,
) -> int:
    """按考试花名册统计学生，不受当前科目成绩是否有效影响。"""
    names = (
        dataframe[name_column]
        .fillna("")
        .astype(str)
        .str.replace("\u3000", "", regex=False)
        .str.strip()
    )
    valid_index = names[(names != "") & (names.str.lower() != "nan")].index
    roster = pd.DataFrame(
        {"姓名": names.loc[valid_index], "分数": 0.0},
        index=valid_index,
    )
    if class_column is not None:
        roster[class_column] = dataframe.loc[valid_index, class_column]
    if student_id_column is not None:
        roster[student_id_column] = dataframe.loc[valid_index, student_id_column]
    records = build_student_identity_records(
        roster,
        class_column=class_column,
        student_id_column=student_id_column,
    )
    return len({record["identity_key"] for record in records})


def resolve_exam_workflow_mode(analysis_mode: str) -> str:
    """将产品层分析视角映射到现有成绩工作流。"""
    return {
        "analysis_center": "single_class",
    }.get(analysis_mode, analysis_mode)


def render_exam_analysis_center(
    *,
    exam_name: str,
    exam_time: str,
    student_count: int,
    class_count: int,
    subject: str,
    data_status: str,
) -> None:
    """渲染当前考试上下文。"""
    st.markdown(
        f"""
        <section class="exam-center-header">
            <div>
                <p class="home-eyebrow">考试分析中心</p>
                <h1 class="home-title">{escape(exam_name)}</h1>
                <p class="home-description">考试时间：{escape(exam_time)}</p>
            </div>
            <div class="exam-center-metrics">
                <div><span>学生人数</span><strong>{int(student_count)}</strong></div>
                <div><span>班级数量</span><strong>{int(class_count)}</strong></div>
                <div><span>分析科目</span><strong>{escape(subject)}</strong></div>
                <div><span>数据状态</span><strong class="exam-status-ready">{escape(data_status)}</strong></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_teacher_view_placeholder() -> None:
    """展示教师视角规划说明，不读取或计算成绩数据。"""
    with st.container(border=True):
        st.markdown(
            """
            <div class="upcoming-feature teacher-view-placeholder">
                <div class="upcoming-feature-icon">👩‍🏫</div>
                <h2>教师视角（规划中）</h2>
                <p>从任课教师角度查看：</p>
                <ul>
                    <li>所教学科整体表现</li>
                    <li>不同班级教学效果</li>
                    <li>学生薄弱知识点分析</li>
                </ul>
                <p>该功能将在后续版本开放。</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_exam_comparison_placeholder() -> None:
    """展示考试变化扩展入口，不接入比较业务流程。"""
    with st.container(border=True):
        st.markdown(
            """
            <div class="upcoming-feature">
                <div class="upcoming-feature-icon">📈</div>
                <h2>选择另一场考试后，查看学生进步、下降和成长趋势。</h2>
                <p>当前阶段保留考试变化入口，后续扩展将接入学生匹配和趋势分析。</p>
                <span>后续扩展</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
