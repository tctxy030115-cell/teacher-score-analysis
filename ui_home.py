"""教师成绩分析助手首页，只负责引导新增考试。"""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import streamlit as st


def render_home_page(
    *,
    on_task_select: Callable,
    current_exam_name: str | None = None,
) -> None:
    """展示产品首页，不触发成绩解析或分析逻辑。"""
    st.markdown(
        """
        <section class="home-hero">
            <div class="home-hero-icon">📊</div>
            <div>
                <p class="home-eyebrow">成绩分析中心</p>
                <h1 class="home-title">教师成绩分析助手</h1>
                <p class="home-subtitle">上传一次考试成绩，自动生成班级、学科和学生分析。</p>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown(
            """
            <div class="task-card-copy">
                <div class="task-card-icon">📥</div>
                <h2 class="task-card-title">📥 新增考试</h2>
                <p class="task-card-description">上传新的 Excel 成绩文件，开始一次完整分析。</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button(
            "开始导入",
            key="home_start_exam_import",
            type="primary",
            on_click=on_task_select,
            args=("single_class",),
            width="stretch",
        )

    st.markdown(
        """
        <div class="home-task-heading">
            <h2>最近分析</h2>
            <p>最近导入的考试会显示在这里。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        if current_exam_name:
            st.markdown(
                f"""
                <div class="task-card-copy">
                    <div class="task-card-icon">📊</div>
                    <h2 class="task-card-title">{escape(current_exam_name)}</h2>
                    <p class="task-card-description">当前会话中的考试分析，可继续查看结果。</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                "返回分析",
                key="home_return_current_exam",
                on_click=on_task_select,
                args=("analysis_center",),
                width="stretch",
            )
        else:
            st.markdown(
                """
                <div class="upcoming-feature">
                    <div class="upcoming-feature-icon">🗂️</div>
                    <h2>暂无考试记录</h2>
                    <p>上传一次成绩后，这里会显示你的分析记录。</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
