"""成绩分析页面的轻量视觉组件，不包含成绩业务逻辑或页面状态。"""

from __future__ import annotations

from html import escape
import re

import streamlit as st

from chart_logic import PLOTLY_FONT_FAMILY, apply_plotly_font_family


_ANCHOR_PATTERN = re.compile(r"[^a-z0-9-]+")
_FONT_FAMILY = PLOTLY_FONT_FAMILY


def inject_global_styles() -> None:
    """集中注入仪表盘样式。

    data-testid 是 Streamlit 内部 DOM 标记，本文件集中使用，便于框架升级时统一维护。
    """
    st.markdown(
        """
        <style>
        :root {
            --dashboard-bg: #F4F7FB;
            --dashboard-card: #FFFFFF;
            --dashboard-primary: #2563EB;
            --dashboard-primary-soft: #EAF2FF;
            --dashboard-text: #172033;
            --dashboard-muted: #64748B;
            --dashboard-border: #E5EAF2;
            --dashboard-shadow: 0 8px 24px rgba(31, 51, 86, 0.055);
        }

        .stApp {
            background: var(--dashboard-bg);
            color: var(--dashboard-text);
        }

        .block-container {
            max-width: 1280px;
            padding-top: 1.5rem;
            padding-bottom: 3rem;
        }

        /* Streamlit 1.59: sidebar 与带边框容器使用内部 data-testid。 */
        section[data-testid="stSidebar"] {
            background: #FBFCFE;
            border-right: 1px solid var(--dashboard-border);
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 1.15rem;
        }

        [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {
            background: var(--dashboard-card);
            border: 1px solid var(--dashboard-border) !important;
            border-radius: 16px !important;
            box-shadow: var(--dashboard-shadow);
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid #E7ECF3;
            border-radius: 12px;
            overflow: hidden;
        }

        .dashboard-header {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1.1rem;
            padding: .35rem .1rem .65rem;
        }

        .dashboard-logo,
        .sidebar-logo {
            display: grid;
            place-items: center;
            flex: 0 0 auto;
            background: var(--dashboard-primary);
            color: white;
            box-shadow: 0 8px 18px rgba(37, 99, 235, .22);
        }

        .dashboard-logo {
            width: 46px;
            height: 46px;
            border-radius: 13px;
            font-size: 1.25rem;
        }

        .dashboard-title {
            margin: 0;
            color: var(--dashboard-text);
            font-size: clamp(1.65rem, 3vw, 2.15rem);
            font-weight: 750;
            line-height: 1.18;
            letter-spacing: -.02em;
        }

        .dashboard-subtitle {
            margin: .35rem 0 0;
            color: var(--dashboard-muted);
            font-size: .98rem;
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: .72rem;
            padding: .2rem .45rem 1.15rem;
            border-bottom: 1px solid var(--dashboard-border);
        }

        .sidebar-logo {
            width: 34px;
            height: 34px;
            border-radius: 9px;
            font-weight: 800;
        }

        .sidebar-brand-title {
            color: var(--dashboard-text);
            font-weight: 750;
            font-size: 1rem;
        }

        .sidebar-brand-caption {
            color: #94A3B8;
            font-size: .72rem;
            margin-top: .08rem;
        }

        .sidebar-nav {
            display: flex;
            flex-direction: column;
            gap: .28rem;
            padding: 1rem .15rem;
        }

        .sidebar-nav a {
            display: flex;
            align-items: center;
            gap: .65rem;
            min-height: 42px;
            padding: .58rem .75rem;
            border-radius: 10px;
            color: #526079 !important;
            font-size: .9rem;
            font-weight: 550;
            text-decoration: none !important;
            transition: background-color .15s ease, color .15s ease;
        }

        .sidebar-nav a:hover,
        .sidebar-nav a.is-active {
            background: var(--dashboard-primary-soft);
            color: #1D4ED8 !important;
        }

        .nav-icon {
            display: inline-grid;
            place-items: center;
            width: 22px;
            height: 22px;
            border-radius: 6px;
            background: #F1F5F9;
            color: #4B6587;
            font-size: .72rem;
            font-weight: 750;
        }

        .sidebar-nav a.is-active .nav-icon {
            background: #DBEAFE;
            color: var(--dashboard-primary);
        }

        .sidebar-mode-title {
            margin: 1rem .45rem .55rem;
            color: #94A3B8;
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .08em;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] button {
            width: 100%;
            justify-content: flex-start;
            min-height: 42px;
            border-radius: 10px;
            font-weight: 650;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] {
            border-left: 4px solid #1D4ED8;
        }

        .sidebar-config-title {
            margin: 1rem .15rem .55rem;
            color: var(--dashboard-text);
            font-size: .86rem;
            font-weight: 750;
        }

        .sidebar-summary-card {
            margin: .85rem 0 .35rem;
            padding: .78rem .85rem;
            border-radius: 12px;
            background: #F1F6FD;
            color: #526079;
            font-size: .79rem;
            line-height: 1.7;
        }

        .sidebar-summary-title {
            margin-bottom: .28rem;
            color: var(--dashboard-text);
            font-size: .86rem;
            font-weight: 750;
        }

        .sidebar-summary-label {
            color: #7C8BA1;
        }

        .sidebar-current-context {
            margin: .45rem .35rem .75rem;
            color: #7C8BA1;
            font-size: .78rem;
            line-height: 1.45;
        }

        .sidebar-footer {
            margin: 1.25rem .45rem 0;
            padding-top: 1rem;
            border-top: 1px solid var(--dashboard-border);
            color: #94A3B8;
            font-size: .76rem;
            line-height: 1.55;
        }

        .section-heading {
            display: flex;
            align-items: flex-start;
            gap: .72rem;
            margin: .05rem 0 .85rem;
        }

        .section-icon {
            display: grid;
            place-items: center;
            width: 30px;
            height: 30px;
            flex: 0 0 30px;
            border-radius: 9px;
            background: var(--dashboard-primary-soft);
            color: var(--dashboard-primary);
            font-size: .8rem;
            font-weight: 800;
        }

        .section-title {
            margin: 0;
            color: var(--dashboard-text);
            font-size: 1.08rem;
            font-weight: 720;
            line-height: 1.35;
        }

        .section-caption,
        .section-note {
            color: var(--dashboard-muted);
            font-size: .89rem;
        }

        .section-caption {
            margin: .16rem 0 0;
        }

        .section-note {
            margin: -.2rem 0 .75rem;
        }

        .metric-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .85rem;
        }

        .metric-card {
            min-height: 108px;
            padding: 1rem 1.05rem;
            border: 1px solid #E7ECF3;
            border-radius: 14px;
            background: #FFFFFF;
            box-shadow: 0 4px 14px rgba(31, 51, 86, .035);
        }

        .metric-card-top {
            display: flex;
            align-items: center;
            gap: .55rem;
            color: var(--dashboard-muted);
            font-size: .8rem;
            font-weight: 620;
        }

        .metric-icon {
            display: grid;
            place-items: center;
            width: 26px;
            height: 26px;
            border-radius: 8px;
            background: var(--dashboard-primary-soft);
            color: var(--dashboard-primary);
            font-size: .72rem;
            font-weight: 800;
        }

        .metric-value {
            margin-top: .62rem;
            color: #14213A;
            font-size: 1.62rem;
            font-weight: 760;
            line-height: 1;
            letter-spacing: -.02em;
        }

        .export-subsection {
            padding: .35rem 0 .8rem;
        }

        .export-subsection + .export-subsection {
            margin-top: .65rem;
            padding-top: 1rem;
            border-top: 1px solid var(--dashboard-border);
        }

        .export-subtitle {
            margin: 0 0 .22rem;
            color: var(--dashboard-text);
            font-size: 1rem;
            font-weight: 700;
        }

        .export-description {
            margin: 0 0 .8rem;
            color: var(--dashboard-muted);
            font-size: .86rem;
        }

        .stButton button,
        .stDownloadButton button {
            min-height: 42px;
            border-radius: 10px;
            border-color: #CBD5E1;
            font-weight: 650;
            transition: border-color .15s ease, color .15s ease, background-color .15s ease;
        }

        .stButton button:hover,
        .stDownloadButton button:hover {
            border-color: var(--dashboard-primary);
            color: #1D4ED8;
        }

        .stButton button[kind="primary"],
        .stDownloadButton button[kind="primary"] {
            background: var(--dashboard-primary);
            border-color: var(--dashboard-primary);
            color: #FFFFFF;
        }

        div[data-testid="stFileUploaderDropzone"] {
            border-radius: 13px;
            border-color: #B9C7DC;
            background: #F8FAFD;
        }

        .dashboard-anchor {
            display: block;
            position: relative;
            top: -1rem;
            visibility: hidden;
        }

        @media (min-width: 721px) {
            section[data-testid="stSidebar"] {
                min-width: 220px;
                max-width: 238px;
            }
        }

        @media (max-width: 980px) {
            .metric-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 720px) {
            .block-container {
                padding: 1rem .85rem 2rem;
            }

            .dashboard-header {
                align-items: flex-start;
            }

            .dashboard-logo {
                width: 40px;
                height: 40px;
            }

            .metric-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: .65rem;
            }

            .metric-card {
                min-height: 98px;
                padding: .85rem;
            }

            .metric-value {
                font-size: 1.35rem;
            }
        }

        @media (max-width: 420px) {
            .metric-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(*, analysis_mode: str, on_mode_change):
    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-logo">▥</div>
            <div>
                <div class="sidebar-brand-title">成绩分析工具</div>
                <div class="sidebar-brand-caption">教育数据仪表盘</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        '<div class="sidebar-mode-title">分析模式</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.button(
        "单班成绩分析",
        key="analysis_mode_single_class",
        type="primary" if analysis_mode == "single_class" else "secondary",
        on_click=on_mode_change,
        args=("single_class",),
        width="stretch",
    )
    st.sidebar.button(
        "多班级对比",
        key="analysis_mode_class_comparison",
        type="primary" if analysis_mode == "class_comparison" else "secondary",
        on_click=on_mode_change,
        args=("class_comparison",),
        width="stretch",
    )
    navigation_items = (
        (
            ("统", "核心统计", "section-overview"),
            ("分", "成绩分布与等级占比", "section-distribution"),
            ("科", "各科平均分", "section-subjects"),
            ("明", "完整成绩明细", "section-details"),
            ("优", "优秀学生", "section-excellent"),
            ("升", "待提升学生", "section-improvement"),
            ("出", "报告导出", "section-export"),
        )
        if analysis_mode == "single_class"
        else (
            ("比", "班级横向对比", "section-class-comparison"),
            ("均", "平均得分率", "section-average-rate"),
            ("及", "及格率对比", "section-pass-rate"),
            ("优", "优秀率对比", "section-excellent-rate"),
            ("级", "等级结构", "section-level-structure"),
            ("结", "自动结论", "section-conclusion"),
        )
    )
    navigation_links = "".join(
        f'<a href="#{anchor}"><span class="nav-icon">{escape(icon)}</span>'
        f'{escape(label)}</a>'
        for icon, label, anchor in navigation_items
    )
    st.sidebar.markdown(
        '<div class="sidebar-mode-title">当前页面导航</div>'
        f'<nav class="sidebar-nav" aria-label="当前页面导航">{navigation_links}</nav>',
        unsafe_allow_html=True,
    )
    current_context_container = st.sidebar.container()
    st.sidebar.button(
        "两次考试对比（即将上线）",
        key="analysis_mode_exam_comparison_upcoming",
        disabled=True,
        width="stretch",
    )
    st.sidebar.markdown(
        '<div class="sidebar-footer">一线教师自用工具 · 持续更新中</div>',
        unsafe_allow_html=True,
    )
    return current_context_container


def render_current_context(context: str) -> None:
    st.markdown(
        f'<div class="sidebar-current-context">当前：{escape(str(context))}</div>',
        unsafe_allow_html=True,
    )


def render_analysis_summary(items: dict[str, object]) -> None:
    rows = "".join(
        '<div><span class="sidebar-summary-label">'
        f'{escape(str(label))}：</span>{escape(str(value))}</div>'
        for label, value in items.items()
    )
    st.markdown(
        '<div class="sidebar-summary-card">'
        '<div class="sidebar-summary-title">当前分析</div>'
        f'{rows}</div>',
        unsafe_allow_html=True,
    )


def render_page_header() -> None:
    st.markdown(
        """
        <header class="dashboard-header">
            <div class="dashboard-logo">▥</div>
            <div>
                <h1 class="dashboard-title">成绩分析工具</h1>
                <p class="dashboard-subtitle">上传 Excel，自动完成成绩统计、可视化分析与 Word 报告。</p>
            </div>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_anchor(anchor_id: str) -> None:
    safe_id = _ANCHOR_PATTERN.sub("", str(anchor_id).lower())
    st.markdown(f'<span id="{safe_id}" class="dashboard-anchor"></span>', unsafe_allow_html=True)


def render_section_header(title: str, icon: str = "•", caption: str | None = None) -> None:
    caption_html = f'<p class="section-caption">{escape(caption)}</p>' if caption else ""
    html = (
        '<div class="section-heading">'
        f'<span class="section-icon">{escape(icon)}</span>'
        '<div>'
        f'<h2 class="section-title">{escape(title)}</h2>'
        f'{caption_html}'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _format_plain_number(value: object) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def render_metric_grid(analysis_result: dict) -> None:
    metrics = (
        ("人", "参考人数", str(int(analysis_result["student_count"]))),
        ("均", "平均分", f'{float(analysis_result["average_score"]):.2f}'),
        ("高", "最高分", _format_plain_number(analysis_result["highest_score"])),
        ("低", "最低分", _format_plain_number(analysis_result["lowest_score"])),
        ("优", "优秀学生", str(int(analysis_result["excellent_count"]))),
        ("升", "不及格人数", str(int(analysis_result["fail_count"]))),
        ("及", "及格率", f'{float(analysis_result["pass_rate"]):.1f}%'),
        ("优", "优秀率", f'{float(analysis_result["excellent_rate"]):.1f}%'),
    )
    cards = "".join(
        '<div class="metric-card">'
        f'<div class="metric-card-top"><span class="metric-icon">{icon}</span>{escape(label)}</div>'
        f'<div class="metric-value">{escape(value)}</div>'
        '</div>'
        for icon, label, value in metrics
    )
    st.markdown(f'<div class="metric-grid">{cards}</div>', unsafe_allow_html=True)


def style_dashboard_figure(figure, *, height: int, preserve_trace_colors: bool = False):
    """只改变现有 Plotly Figure 的展示属性，保留全部数据与追踪对象。"""
    top_margin = max(62, figure.layout.margin.t or 0)
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        font={"family": _FONT_FAMILY, "color": "#475569", "size": 13},
        title={"font": {"family": _FONT_FAMILY, "color": "#172033", "size": 18}},
        margin={"l": 52, "r": 32, "t": top_margin, "b": 54},
        hoverlabel={"bgcolor": "#FFFFFF", "font_color": "#334155"},
        legend={"font": {"family": _FONT_FAMILY, "size": 12, "color": "#475569"}},
    )
    figure.update_xaxes(
        color="#64748B",
        linecolor="#D9E2EE",
        tickfont={"family": _FONT_FAMILY, "size": 12},
        title_font={"family": _FONT_FAMILY, "size": 13},
    )
    figure.update_yaxes(
        color="#64748B",
        linecolor="#D9E2EE",
        gridcolor="#E8EEF6",
        tickfont={"family": _FONT_FAMILY, "size": 12},
        title_font={"family": _FONT_FAMILY, "size": 13},
    )
    if not preserve_trace_colors:
        for trace in figure.data:
            if trace.type == "bar":
                trace.update(marker={"color": "#4F8DE8", "line": {"color": "#2563EB", "width": 1}})
            elif trace.type == "pie":
                trace.update(
                    marker={
                        "colors": ["#BFD5F5", "#9ABCEB", "#719FE1", "#4F84D7", "#2563EB"],
                        "line": {"color": "#FFFFFF", "width": 2},
                    }
                )
    return apply_plotly_font_family(figure)
