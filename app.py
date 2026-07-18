from copy import deepcopy
from dataclasses import replace
from functools import partial
from hashlib import sha256
from math import isfinite
from pathlib import Path

import pandas as pd
import streamlit as st

from class_comparison_logic import (
    ClassComparisonResult,
    FAIRNESS_NOTICE,
    build_average_rate_figure,
    build_class_comparison,
    build_comparison_conclusion,
    build_level_structure_figure,
    build_pass_excellent_figure,
    natural_sort_class_names,
)
from chart_logic import (
    build_invalid_data_warning,
    build_distribution_figure,
    build_level_donut_figure,
    build_subject_average_figure,
    calculate_score_distribution,
    calculate_subject_averages,
    classify_score_rows,
    count_invalid_reasons,
)
from grade_logic import (
    CLASS_COLUMN_ALIASES,
    NAME_COLUMN_ALIASES,
    analyze_scores,
    build_full_score_widget_key,
    build_score_column_options,
    build_full_score_context_key,
    initialize_full_score_widget_state,
    build_dataframe_from_header,
    build_single_class_options,
    clean_column_name,
    create_single_score_template,
    detect_header_row,
    export_score_result_to_bytes,
    filter_dataframe_by_class,
    find_first_matching_column,
    find_first_matching_score_column,
    format_class_value,
    get_full_score_suggestion,
    get_total_score_notice,
    has_analyzable_columns,
    normalize_excellent_percent,
    resolve_column_selection,
    resolve_single_class_selection,
    set_column_full_score_safely,
)
from report_logic import (
    ReportGenerationError,
    build_score_report_bytes,
    safe_report_filename,
)
from models import ExamContext, PageState, ResultPayload, SubjectConfig
from services import (
    ExamColumnMapping,
    ExamImportDraft,
    ExamImportError,
    ExamImportService,
    GradeOverviewContextError,
    ResultStore,
    analysis_result_to_legacy_dict,
    build_analysis_request,
    build_exam_config,
    build_exam_context,
    build_grade_overview_dataframe,
    build_grade_overview_identity_records,
    effective_config,
    get_or_build_class_result,
    get_or_build_report_result,
    get_or_build_subject_result,
)
from student_identity import (
    build_display_score_details,
    build_display_student_list,
    build_student_identity_records,
    build_student_score_mapping,
    find_student_id_column,
    restore_analysis_result_display_names,
)
from ui_components import (
    inject_global_styles,
    render_anchor,
    render_current_context,
    render_metric_grid,
    render_page_header,
    render_section_header,
    render_sidebar,
    render_workflow_steps,
    style_dashboard_figure,
)
from ui_exam_center import (
    activate_analysis_center,
    cache_current_exam,
    cache_current_exam_snapshot,
    count_exam_classes,
    count_exam_students,
    render_analysis_center_top,
    render_exam_analysis_center,
    render_exam_comparison_placeholder,
    render_teacher_view_placeholder,
    resolve_exam_workflow_mode,
    restore_current_exam_file,
)
from ui_home import render_home_page


st.set_page_config(
    page_title="教师成绩分析助手",
    page_icon="📊",
    layout="wide",
)

st.session_state.setdefault("analysis_mode", "home")
analysis_mode = st.session_state["analysis_mode"]
on_task_select = partial(st.session_state.__setitem__, "analysis_mode")

inject_global_styles()
sidebar_context = render_sidebar(
    analysis_mode=analysis_mode,
    on_mode_change=on_task_select,
)

if analysis_mode == "home":
    with sidebar_context:
        render_current_context("首页")
    current_exam_name = None
    if st.session_state.get("current_exam_file_bytes"):
        current_exam_name = Path(
            st.session_state.get("current_exam_file_name", "本次考试")
        ).stem
    render_home_page(
        on_task_select=on_task_select,
        current_exam_name=current_exam_name,
    )
    st.stop()

if analysis_mode == "exam_comparison":
    with sidebar_context:
        render_current_context("成绩变化 · 后续扩展")
    render_page_header(
        title="两次考试变化",
        subtitle="上传两次考试成绩，分析学生变化趋势。",
        icon="📈",
    )
    render_workflow_steps(("上传第一次考试", "上传第二次考试", "确认学生匹配", "查看变化趋势"))
    render_exam_comparison_placeholder()
    st.stop()

if analysis_mode == "teacher_view":
    with sidebar_context:
        render_current_context("教师视角 · 规划中")
    render_page_header(
        title="教师视角（规划中）",
        subtitle="从任课教师角度查看所教学科和班级表现。",
        icon="👩‍🏫",
    )
    render_teacher_view_placeholder()
    st.stop()

if analysis_mode == "analysis_center" and not st.session_state.get(
    "current_exam_file_bytes"
):
    st.session_state["analysis_mode"] = "single_class"
    st.rerun()

workflow_mode = resolve_exam_workflow_mode(analysis_mode)
analysis_center_slot = st.empty() if analysis_mode == "analysis_center" else None
if analysis_mode == "report_center":
    render_page_header(
        title="生成教学报告",
        subtitle="完成成绩分析后，继续使用现有 Word 报告生成流程。",
        icon="📄",
    )
    snapshot = st.session_state.get("current_exam_snapshot")
    if not snapshot:
        with sidebar_context:
            render_current_context("等待完成成绩分析")
        st.info("请先上传成绩表并完成分析，再进入报告中心生成 Word 教学报告。")
        st.stop()

    structured_report_result = None
    current_exam_context = st.session_state.get("current_exam_context")
    current_exam_config = st.session_state.get("current_exam_config")
    current_page_state = st.session_state.get("current_page_state")
    if (
        current_exam_context is not None
        and current_exam_config is not None
        and current_page_state is not None
    ):
        try:
            report_page_state = replace(
                current_page_state,
                page_name="report_center",
                selected_subject=snapshot["score_col"],
                selected_classes=(
                    ()
                    if snapshot["selected_class"] == "全部学生"
                    else (str(snapshot["selected_class"]),)
                ),
                config_overrides={},
            )
            report_request = build_analysis_request(
                current_exam_context,
                current_exam_config,
                report_page_state,
            )
            result_store = st.session_state.get("result_store")
            if not isinstance(result_store, ResultStore):
                result_store = ResultStore()
                st.session_state["result_store"] = result_store
            structured_report_result = get_or_build_report_result(
                report_request,
                result_store,
                snapshot["analysis_result"],
            )
        except (AttributeError, TypeError, ValueError):
            structured_report_result = None
    report_analysis_result = analysis_result_to_legacy_dict(
        structured_report_result,
        fallback=snapshot["analysis_result"],
    )

    with sidebar_context:
        render_current_context(
            f'{snapshot["selected_class"]} · {snapshot["score_col"]}'
        )
    st.caption(
        f'当前范围：{snapshot["selected_class"]} · '
        f'成绩列：{snapshot["score_col"]} · '
        f'满分：{float(snapshot["full_score"]):g} 分 · '
        f'优秀线：{float(snapshot["excellent_percent"]):g}%'
    )
    with st.container(border=True):
        render_section_header(
            "Word 成绩分析报告",
            "报",
            "使用当前考试已经生成的分析结果，不重新解析或计算成绩。",
        )
        school_name = st.text_input("学校名称", key="word_report_school_name")
        report_name = st.text_input(
            "报告名称",
            value=snapshot["report_name"],
            key="word_report_exam_name",
        )
        report_signature = (
            "current_exam_snapshot",
            snapshot["score_context_key"],
            snapshot["selected_class"],
            snapshot["score_col"],
            float(snapshot["full_score"]),
            float(snapshot["excellent_percent"]),
            school_name,
            report_name,
        )
        if st.session_state.get("word_report_signature") != report_signature:
            st.session_state.pop("word_report_bytes", None)
            st.session_state.pop("word_report_filename", None)
            st.session_state.pop("word_report_signature", None)

        if st.button("生成 Word 报告", type="primary", width="stretch"):
            try:
                report_bytes = build_score_report_bytes(
                    analysis_result=report_analysis_result,
                    excellent_df=snapshot["excellent_df"],
                    fail_df=snapshot["fail_df"],
                    distribution=snapshot["distribution"],
                    distribution_figure=snapshot["distribution_figure"],
                    level_figure=snapshot["level_figure"],
                    subject_average_figure=snapshot["subject_average_figure"],
                    selected_class=snapshot["selected_class"],
                    score_col=snapshot["score_col"],
                    full_score=snapshot["full_score"],
                    school_name=school_name,
                    exam_name=report_name,
                )
                st.session_state["word_report_bytes"] = report_bytes
                st.session_state["word_report_filename"] = safe_report_filename(
                    school_name=school_name,
                    class_name=snapshot["selected_class"],
                    subject_name=snapshot["score_col"],
                    exam_name=report_name,
                )
                st.session_state["word_report_signature"] = report_signature
            except ReportGenerationError as exc:
                st.error(str(exc))

        if st.session_state.get("word_report_signature") == report_signature:
            report_bytes = st.session_state.get("word_report_bytes")
            if report_bytes:
                st.success("Word 报告生成成功，可点击下方按钮下载。")
                st.download_button(
                    "下载 Word 成绩分析报告",
                    data=report_bytes,
                    file_name=st.session_state["word_report_filename"],
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    width="stretch",
                )
    st.stop()
elif analysis_mode == "subject_analysis":
    render_page_header(
        title="学科分析",
        subtitle="查看当前学科表现，分析优势和薄弱环节。",
        icon="📚",
    )
elif workflow_mode == "class_comparison":
    render_page_header(
        title="班级比较",
        subtitle="比较不同班级成绩差异，发现优势与提升空间。",
        icon="🏫",
    )
elif analysis_mode != "analysis_center":
    render_page_header(
        title="单次成绩分析",
        subtitle="分析一次考试成绩，查看均分、分布、等级和学生名单。",
        icon="📊",
    )

if analysis_mode != "analysis_center":
    if analysis_mode == "subject_analysis":
        workflow_steps = ("选择科目", "查看指标", "班级对比", "等级结构")
    elif workflow_mode == "class_comparison":
        workflow_steps = ("上传成绩", "数据确认", "班级比较", "查看结论")
    else:
        workflow_steps = ("上传成绩", "数据确认", "分析结果", "导出报告")
    render_workflow_steps(workflow_steps)


def initialize_class_analysis_state(session_state, snapshot):
    score_options = list(snapshot.get("score_options") or [])
    preferred_score_col = resolve_column_selection(
        score_options,
        session_state.get("class_analysis_score_column"),
        snapshot.get("score_col"),
    )
    previous_score_col = session_state.get("class_analysis_score_column")
    session_state["class_analysis_score_column"] = preferred_score_col

    full_score_by_column = snapshot.get("full_score_by_column") or {}
    if (
        previous_score_col != preferred_score_col
        or "class_analysis_full_score" not in session_state
    ):
        session_state["class_analysis_full_score"] = float(
            full_score_by_column.get(
                clean_column_name(preferred_score_col),
                get_full_score_suggestion(preferred_score_col).value,
            )
        )
    session_state.setdefault(
        "class_analysis_excellent_percent",
        float(snapshot.get("excellent_percent", 90.0)),
    )
    return preferred_score_col


def reset_class_analysis_full_score(snapshot):
    score_col = st.session_state.get("class_analysis_score_column")
    full_score_by_column = snapshot.get("full_score_by_column") or {}
    st.session_state["class_analysis_full_score"] = float(
        full_score_by_column.get(
            clean_column_name(score_col),
            get_full_score_suggestion(score_col).value,
        )
    )


def build_class_analysis_dataframe(snapshot, score_col):
    identity_records_by_index = snapshot.get("identity_records_by_index")
    subject_scores_by_index = snapshot.get("subject_scores_by_index")
    name_col = snapshot.get("name_col")
    class_col = snapshot.get("class_col")
    if not identity_records_by_index:
        raise ValueError("当前考试快照缺少学生身份映射。")
    if not subject_scores_by_index:
        raise ValueError("当前考试快照缺少学科成绩数据。")
    if name_col is None or class_col is None:
        raise ValueError("当前考试未识别到姓名列或班级列。")

    row_indexes = []
    row_records = []
    for row_index, identity_record in identity_records_by_index.items():
        row_scores = subject_scores_by_index.get(row_index)
        if row_scores is None or score_col not in row_scores:
            raise ValueError("学生身份与学科成绩无法按原始行索引对应。")
        row_indexes.append(row_index)
        row_records.append(
            {
                class_col: identity_record["班级"],
                name_col: identity_record["姓名"],
                score_col: row_scores[score_col],
            }
        )
    return pd.DataFrame(row_records, index=row_indexes)


def build_class_analysis_comparison(
    snapshot,
    *,
    score_col,
    selected_classes,
    full_score,
    excellent_percent,
):
    dataframe = build_class_analysis_dataframe(snapshot, score_col)
    result = build_class_comparison(
        dataframe,
        class_column=snapshot["class_col"],
        name_column=snapshot["name_col"],
        score_column=score_col,
        selected_classes=selected_classes,
        full_score=full_score,
        excellent_percent=excellent_percent,
    )
    return dataframe, result


def render_class_comparison_section(
    *,
    result,
    score_col,
    full_score,
    excellent_percent,
    selected_classes,
):
    render_anchor("section-class-comparison")
    with st.container(border=True):
        render_section_header(
            "班级横向对比",
            "比",
            "选择两个或多个班级，对比同一成绩列下的平均得分率、及格率、优秀率和等级结构。",
        )
        st.caption(
            f"数据口径：当前考试 · {score_col} · 满分 {float(full_score):g} 分 · "
            f"及格线 60% · 优秀线 {float(excellent_percent):g}%"
        )
        if len(selected_classes) > 10:
            st.warning("当前选择的班级较多，图表标签可能较密集；可减少班级数量以便阅读。")
        if len(selected_classes) < 2:
            st.info("请至少选择两个班级后生成对比。")
            return

        if not result.excluded.empty:
            st.warning("以下班级没有有效成绩，已从数值对比、图表和自动结论中排除。")
            st.dataframe(result.excluded, width="stretch", hide_index=True)
        if not result.is_comparable:
            st.info("排除无有效成绩的班级后，可比较的班级不足两个，暂不生成对比图表。")
            return

        display_columns = [
            "班级",
            "原始记录数",
            "有效人数",
            "跳过人数",
            "平均分",
            "平均得分率",
            "最高分",
            "最低分",
            "及格率",
            "优秀率",
            "待提升率",
        ]
        st.dataframe(
            result.summary[display_columns],
            width="stretch",
            hide_index=True,
            column_config={
                "原始记录数": st.column_config.NumberColumn(format="%d"),
                "有效人数": st.column_config.NumberColumn(format="%d"),
                "跳过人数": st.column_config.NumberColumn(format="%d"),
                "平均分": st.column_config.NumberColumn(format="%.2f"),
                "平均得分率": st.column_config.NumberColumn(format="%.1f%%"),
                "最高分": st.column_config.NumberColumn(format="%.2f"),
                "最低分": st.column_config.NumberColumn(format="%.2f"),
                "及格率": st.column_config.NumberColumn(format="%.1f%%"),
                "优秀率": st.column_config.NumberColumn(format="%.1f%%"),
                "待提升率": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

        chart_config = {"displayModeBar": False, "displaylogo": False}

        average_rate_figure = build_average_rate_figure(result.summary)
        render_anchor("section-average-rate")
        style_dashboard_figure(
            average_rate_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            average_rate_figure,
            width="stretch",
            config=chart_config,
        )

        pass_excellent_figure = build_pass_excellent_figure(result.summary)
        render_anchor("section-pass-rate")
        render_anchor("section-excellent-rate")
        style_dashboard_figure(
            pass_excellent_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            pass_excellent_figure,
            width="stretch",
            config=chart_config,
        )

        level_structure_figure = build_level_structure_figure(result.levels)
        render_anchor("section-level-structure")
        style_dashboard_figure(
            level_structure_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            level_structure_figure,
            width="stretch",
            config=chart_config,
        )

        render_anchor("section-conclusion")
        st.markdown("#### 自动对比结论")
        st.write(build_comparison_conclusion(result.summary))
        st.info(FAIRNESS_NOTICE)


def build_exam_identity_snapshot(
    dataframe,
    *,
    name_col,
    class_col,
    student_id_col,
    score_options,
):
    if not dataframe.index.is_unique:
        raise ValueError("原始成绩表行索引不唯一，无法建立稳定的学生身份关联。")

    identity_columns = [name_col]
    if class_col is not None and class_col not in identity_columns:
        identity_columns.insert(0, class_col)
    if student_id_col is not None and student_id_col not in identity_columns:
        identity_columns.insert(0, student_id_col)

    identity_rows = dataframe[identity_columns].copy()
    placeholder_scores = pd.Series(0.0, index=dataframe.index)
    classified_identities = classify_score_rows(
        identity_rows[name_col],
        placeholder_scores,
        full_score=1.0,
    )
    identity_rows["姓名"] = classified_identities["姓名"]
    identity_rows["分数"] = classified_identities["分数"]
    valid_identity_rows = identity_rows[
        classified_identities["无效原因"].isna()
    ].copy()
    identity_records = build_student_identity_records(
        valid_identity_rows,
        class_column=class_col,
        student_id_column=student_id_col,
    )
    identity_records_by_index = dict(
        zip(valid_identity_rows.index, identity_records)
    )
    subject_scores_by_index = {
        row_index: {
            score_column: dataframe.at[row_index, score_column]
            for score_column in score_options
        }
        for row_index in identity_records_by_index
    }
    return identity_records_by_index, subject_scores_by_index


def ensure_current_exam_context(
    session_state,
    *,
    service,
    file_content,
    file_name,
    sheet_names,
    sheet_name,
    detected_header_row,
    header_row_index,
    dataframe,
    column_mapping,
    exam_name,
):
    """字段确认后提前建立 Context；失败时由后续旧 builder 继续兜底。"""

    file_fingerprint = sha256(file_content).hexdigest()
    existing_context = session_state.get("current_exam_context")
    if (
        isinstance(existing_context, ExamContext)
        and existing_context.metadata.file_fingerprint == file_fingerprint
        and existing_context.metadata.sheet_name == sheet_name
        and existing_context.schema.name_column == column_mapping.name_column
        and existing_context.schema.class_column == column_mapping.class_column
        and existing_context.schema.student_id_column
        == column_mapping.student_id_column
        and existing_context.schema.score_columns == column_mapping.score_columns
    ):
        return existing_context

    draft = ExamImportDraft(
        file_content=file_content,
        file_name=file_name,
        file_fingerprint=file_fingerprint,
        sheet_names=tuple(sheet_names),
        selected_sheet=sheet_name,
        detected_header_row=detected_header_row,
        header_row_index=header_row_index,
        dataframe=dataframe,
        suggested_mapping=column_mapping,
    )
    try:
        current_exam_context = service.build_context(
            draft,
            column_mapping,
            exam_name=exam_name,
        )
    except (ExamImportError, TypeError, ValueError):
        return None
    session_state["current_exam_context"] = current_exam_context
    return current_exam_context


def resolve_grade_overview_fact_source(legacy_dataframe, current_exam_context):
    """Context 必须能完整覆盖旧表行，才能原子切换年级总览事实来源。"""

    if current_exam_context is None:
        return legacy_dataframe, None
    try:
        context_dataframe = build_grade_overview_dataframe(current_exam_context)
    except (GradeOverviewContextError, KeyError, TypeError, ValueError):
        return legacy_dataframe, None
    if not context_dataframe.index.equals(legacy_dataframe.index):
        return legacy_dataframe, None
    return context_dataframe, current_exam_context


def prepare_grade_overview_identity_records(
    grade_overview_context,
    valid_scores,
    *,
    score_col,
    class_col,
    student_id_col,
):
    """Context 路径只按 index 取已有身份；缺失 Context 时完整走旧身份流程。"""

    if grade_overview_context is not None:
        return build_grade_overview_identity_records(
            grade_overview_context,
            score_col,
            valid_scores.index,
        )
    return build_student_identity_records(
        valid_scores,
        class_column=class_col,
        student_id_column=student_id_col,
    )


GRADE_OVERVIEW_OVERRIDE_NAMESPACE = "__grade_overview__"


def read_grade_overview_overrides(page_state, exam_id):
    """读取年级总览命名空间内的临时规则，并返回独立副本。"""

    if not isinstance(page_state, PageState) or page_state.exam_id != exam_id:
        return {}
    scoped_overrides = page_state.config_overrides.get(
        GRADE_OVERVIEW_OVERRIDE_NAMESPACE
    )
    if isinstance(scoped_overrides, dict):
        return deepcopy(scoped_overrides)
    return {}


def resolve_grade_overview_rule_source(
    exam_context,
    exam_config,
    current_page_state,
    subject,
    selected_class,
    system_default,
):
    """原子解析年级规则；任何新架构对象不可用时返回 None。"""

    if (
        exam_context is None
        or exam_config is None
        or not isinstance(current_page_state, PageState)
        or getattr(exam_config, "exam_id", None) != exam_context.exam_id
    ):
        return None

    existing_overrides = read_grade_overview_overrides(
        current_page_state,
        exam_context.exam_id,
    )
    selected_classes = (
        () if selected_class == "全部学生" else (str(selected_class),)
    )
    provisional_page_state = replace(
        current_page_state,
        exam_id=exam_context.exam_id,
        page_name="grade_overview",
        selected_subject=subject,
        selected_classes=selected_classes,
        config_overrides=existing_overrides,
    )
    base_page_state = replace(provisional_page_state, config_overrides={})
    try:
        base_config = effective_config(
            exam_config,
            base_page_state,
            subject,
            system_default,
        )
        resolved_config = effective_config(
            exam_config,
            provisional_page_state,
            subject,
            system_default,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if float(resolved_config.pass_percent) != 60.0:
        return None

    reset_widgets = not (
        current_page_state.exam_id == exam_context.exam_id
        and current_page_state.page_name == "grade_overview"
        and current_page_state.selected_subject == subject
    )
    return (
        base_config,
        resolved_config,
        provisional_page_state,
        existing_overrides,
        reset_widgets,
    )


def sanitize_grade_overview_widget_rules(
    widget_full_score,
    widget_excellent_percent,
    resolved_config,
):
    """异常 widget 值不覆盖已经解析出的有效业务规则。"""

    try:
        numeric_full_score = float(widget_full_score)
    except (TypeError, ValueError):
        numeric_full_score = float(resolved_config.full_score)
    if not isfinite(numeric_full_score) or numeric_full_score < 10.0:
        numeric_full_score = float(resolved_config.full_score)

    try:
        numeric_excellent_percent = float(widget_excellent_percent)
    except (TypeError, ValueError):
        numeric_excellent_percent = float(resolved_config.excellent_percent)
    if (
        not isfinite(numeric_excellent_percent)
        or not 0.0 <= numeric_excellent_percent <= 100.0
        or numeric_excellent_percent == 1.0
    ):
        numeric_excellent_percent = float(resolved_config.excellent_percent)
    return numeric_full_score, numeric_excellent_percent


def update_grade_overview_page_state(
    provisional_page_state,
    existing_overrides,
    *,
    subject,
    selected_class,
    full_score,
    excellent_percent,
    base_config,
):
    """将合法页面调整保存到年级命名空间，不修改 ExamConfig。"""

    updated_overrides = deepcopy(existing_overrides)
    subject_key = clean_column_name(subject)
    subject_override = {}
    if float(full_score) != float(base_config.full_score):
        subject_override["full_score"] = float(full_score)
    if float(excellent_percent) != float(base_config.excellent_percent):
        subject_override["excellent_percent"] = float(excellent_percent)
    if subject_override:
        updated_overrides[subject_key] = subject_override
    else:
        updated_overrides.pop(subject_key, None)

    selected_classes = (
        () if selected_class == "全部学生" else (str(selected_class),)
    )
    local_page_state = replace(
        provisional_page_state,
        selected_subject=subject,
        selected_classes=selected_classes,
        config_overrides=updated_overrides,
    )
    return replace(
        local_page_state,
        config_overrides={
            GRADE_OVERVIEW_OVERRIDE_NAMESPACE: updated_overrides,
        },
    )


def bind_subject_scores_by_row_index(valid_scores, identity_records_by_index):
    score_records = []
    for row_index, row in valid_scores.iterrows():
        identity_record = identity_records_by_index.get(row_index)
        if identity_record is None:
            raise KeyError(row_index)
        score_record = dict(identity_record)
        score_record["分数"] = float(row["分数"])
        score_records.append(score_record)
    return build_student_score_mapping(score_records)


def initialize_subject_analysis_parameters(session_state, snapshot, score_col):
    context_key = snapshot.get("score_context_key")
    if not context_key:
        raise ValueError("当前考试快照缺少参数上下文。")

    cleaned_score_col = clean_column_name(score_col)
    full_score_settings = session_state.setdefault(
        "subject_analysis_full_score_by_context",
        {},
    )
    excellent_settings = session_state.setdefault(
        "subject_analysis_excellent_percent_by_context",
        {},
    )
    context_full_scores = full_score_settings.setdefault(context_key, {})
    context_excellent_percents = excellent_settings.setdefault(context_key, {})

    if cleaned_score_col not in context_full_scores:
        snapshot_full_scores = snapshot.get("full_score_by_column") or {}
        context_full_scores[cleaned_score_col] = float(
            snapshot_full_scores.get(
                cleaned_score_col,
                get_full_score_suggestion(score_col).value,
            )
        )
    if cleaned_score_col not in context_excellent_percents:
        context_excellent_percents[cleaned_score_col] = 90.0
    return (
        float(context_full_scores[cleaned_score_col]),
        float(context_excellent_percents[cleaned_score_col]),
    )


def build_subject_analysis_comparison(
    dataframe,
    *,
    class_col,
    name_col,
    score_col,
    selected_classes,
    full_score,
    excellent_percent,
):
    return build_class_comparison(
        dataframe,
        class_column=class_col,
        name_column=name_col,
        score_column=score_col,
        selected_classes=selected_classes,
        full_score=full_score,
        excellent_percent=excellent_percent,
    )


def render_subject_analysis_page(snapshot):
    identity_records_by_index = snapshot.get("identity_records_by_index")
    subject_scores_by_index = snapshot.get("subject_scores_by_index")
    name_col = snapshot.get("name_col")
    class_col = snapshot.get("class_col")
    student_id_col = snapshot.get("student_id_col")
    score_options = list(snapshot.get("score_options") or [])
    if not identity_records_by_index:
        st.error("当前考试快照缺少学生身份映射，请返回年级总览重新完成分析。")
        return
    if not subject_scores_by_index or name_col is None or not score_options:
        st.info("当前考试快照缺少可用于学科分析的数据，请返回年级总览重新完成分析。")
        return

    preferred_score_col = resolve_column_selection(
        score_options,
        st.session_state.get("subject_analysis_score_column"),
        snapshot.get("score_col"),
    )
    if st.session_state.get("subject_analysis_score_column") != preferred_score_col:
        st.session_state["subject_analysis_score_column"] = preferred_score_col

    with st.container(border=True):
        render_section_header(
            "学科分析设置",
            "设",
            "各科满分和优秀线独立保存，不修改年级总览、班级分析或报告中心参数。",
        )
        settings_columns = st.columns(4)
        score_col = settings_columns[0].selectbox(
            "分析科目",
            score_options,
            key="subject_analysis_score_column",
        )
        try:
            configured_full_score, configured_excellent_percent = (
                initialize_subject_analysis_parameters(
                    st.session_state,
                    snapshot,
                    score_col,
                )
            )
        except ValueError as exc:
            st.error(f"读取学科分析参数失败：{exc}")
            return

        context_key = snapshot["score_context_key"]
        cleaned_score_col = clean_column_name(score_col)
        full_score_widget_key = (
            f"subject_analysis::full_score::{context_key}::{cleaned_score_col}"
        )
        excellent_widget_key = (
            f"subject_analysis::excellent_percent::{context_key}::{cleaned_score_col}"
        )
        if full_score_widget_key not in st.session_state:
            st.session_state[full_score_widget_key] = configured_full_score
        if excellent_widget_key not in st.session_state:
            st.session_state[excellent_widget_key] = configured_excellent_percent

        full_score = settings_columns[1].number_input(
            "满分",
            min_value=1.0,
            step=1.0,
            key=full_score_widget_key,
        )
        with settings_columns[2]:
            st.metric("及格线", "60%", help="及格线固定为满分的60%，当前不可编辑。")
        excellent_percent = settings_columns[3].number_input(
            "优秀线（%）",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=excellent_widget_key,
        )
        st.session_state["subject_analysis_full_score_by_context"][context_key][
            cleaned_score_col
        ] = float(full_score)
        st.session_state[
            "subject_analysis_excellent_percent_by_context"
        ][context_key][cleaned_score_col] = float(excellent_percent)

    effective_excellent_percent = normalize_excellent_percent(excellent_percent)
    if excellent_percent < 60:
        st.warning("优秀线不能低于及格线60%，本次学科分析将按60%处理。")

    subject_row_indexes = []
    subject_row_records = []
    for row_index, identity_record in identity_records_by_index.items():
        row_scores = subject_scores_by_index.get(row_index)
        if row_scores is None or score_col not in row_scores:
            st.error("当前考试快照的学生身份与学科成绩无法按原始行索引对应，请返回年级总览重新完成分析。")
            return
        row_record = {
            name_col: identity_record["姓名"],
            score_col: row_scores[score_col],
        }
        if class_col is not None:
            row_record[class_col] = identity_record["班级"]
        if student_id_col is not None:
            row_record[student_id_col] = identity_record["学号"]
        subject_row_indexes.append(row_index)
        subject_row_records.append(row_record)
    subject_rows = pd.DataFrame(subject_row_records, index=subject_row_indexes)
    classified_rows = classify_score_rows(
        subject_rows[name_col],
        subject_rows[score_col],
        full_score=full_score,
    )
    subject_rows["姓名"] = classified_rows["姓名"]
    subject_rows["分数"] = classified_rows["分数"]
    subject_rows["无效原因"] = classified_rows["无效原因"]
    valid_scores = subject_rows[subject_rows["无效原因"].isna()].copy()

    invalid_warning = build_invalid_data_warning(
        count_invalid_reasons(classified_rows),
        full_score,
    )
    if invalid_warning:
        st.warning(invalid_warning)
    if valid_scores.empty:
        st.info("当前科目没有可用于分析的有效成绩。")
        return

    missing_identity_indexes = [
        row_index
        for row_index in valid_scores.index
        if row_index not in identity_records_by_index
    ]
    if missing_identity_indexes:
        st.error("当前考试快照的学生身份映射不完整，请返回年级总览重新完成分析。")
        return
    try:
        subject_score_mapping = bind_subject_scores_by_row_index(
            valid_scores,
            identity_records_by_index,
        )
    except (KeyError, ValueError) as exc:
        st.error(f"学科成绩绑定学生身份失败：{exc}")
        return
    subject_analysis_result = analyze_scores(
        subject_score_mapping,
        full_score=full_score,
        excellent_percent=effective_excellent_percent,
        current_class="全部学生",
        current_subject=score_col,
    )
    render_anchor("section-subject-metrics")
    with st.container(border=True):
        render_section_header("学科指标", "统", f"当前科目：{score_col}")
        render_metric_grid(subject_analysis_result)

    render_anchor("section-subject-class-comparison")
    with st.container(border=True):
        render_section_header(
            "班级对比",
            "比",
            "对比当前学科在各班的平均得分率。",
        )
        if class_col is None:
            st.info("当前考试未识别到班级列，暂无法生成班级对比图。")
            return
        class_options = natural_sort_class_names(subject_rows[class_col])
        if len(class_options) < 2:
            st.info("当前考试不足两个有效班级，暂无法生成班级对比图。")
            return

        comparison = build_subject_analysis_comparison(
            subject_rows,
            class_col=class_col,
            name_col=name_col,
            score_col=score_col,
            selected_classes=class_options,
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
        )
        if not comparison.excluded.empty:
            st.warning("部分班级没有有效成绩，已从学科班级对比图中排除。")
        if not comparison.is_comparable:
            st.info("排除无有效成绩的班级后，可比较班级不足两个。")
            return

        chart_config = {"displayModeBar": False, "displaylogo": False}
        average_rate_figure = build_average_rate_figure(comparison.summary)
        style_dashboard_figure(
            average_rate_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            average_rate_figure,
            width="stretch",
            config=chart_config,
        )

        render_anchor("section-subject-level-structure")
        level_structure_figure = build_level_structure_figure(comparison.levels)
        style_dashboard_figure(
            level_structure_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            level_structure_figure,
            width="stretch",
            config=chart_config,
        )


def calculate_subject_analysis_payload(
    exam_context,
    *,
    score_col,
    selected_classes,
    full_score,
    excellent_percent,
):
    """调用现有计算函数，返回可缓存且不包含 figure 的旧结果字典。"""

    identity_records_by_index = exam_context.identity_records_by_index
    subject_scores_by_index = exam_context.subject_scores_by_index
    name_col = exam_context.schema.name_column
    class_col = exam_context.schema.class_column
    student_id_col = exam_context.schema.student_id_column
    if not identity_records_by_index:
        raise ValueError("当前考试档案缺少学生身份映射。")
    if not subject_scores_by_index or name_col is None:
        raise ValueError("当前考试档案缺少可用于学科分析的数据。")

    row_indexes = []
    row_records = []
    for row_index, identity_record in identity_records_by_index.items():
        row_scores = subject_scores_by_index.get(row_index)
        if row_scores is None or score_col not in row_scores:
            raise ValueError("学生身份与学科成绩无法按原始行索引对应。")
        row_record = {
            name_col: identity_record["姓名"],
            score_col: row_scores[score_col],
        }
        if class_col is not None:
            row_record[class_col] = identity_record["班级"]
        if student_id_col is not None:
            row_record[student_id_col] = identity_record["学号"]
        row_indexes.append(row_index)
        row_records.append(row_record)

    subject_rows = pd.DataFrame(row_records, index=row_indexes)
    classified_rows = classify_score_rows(
        subject_rows[name_col],
        subject_rows[score_col],
        full_score=full_score,
    )
    subject_rows["姓名"] = classified_rows["姓名"]
    subject_rows["分数"] = classified_rows["分数"]
    subject_rows["无效原因"] = classified_rows["无效原因"]
    valid_scores = subject_rows[subject_rows["无效原因"].isna()].copy()
    invalid_warning = build_invalid_data_warning(
        count_invalid_reasons(classified_rows),
        full_score,
    )

    base_result = {
        "summary": {
            "current_subject": score_col,
            "analysis_scope": "全部学生",
        },
        "metrics": {},
        "tables": {
            "class_comparison": pd.DataFrame(),
            "comparison_levels": pd.DataFrame(),
            "comparison_excluded": pd.DataFrame(),
            "score_details": [],
            "excellent_students": [],
            "fail_students": [],
        },
        "charts": {
            "class_average_rate_data": pd.DataFrame(),
            "level_structure_data": pd.DataFrame(),
        },
        "extra": {
            "invalid_warning": invalid_warning,
            "comparison_status": "not_calculated",
            "legacy_analysis_result": {},
        },
    }
    if valid_scores.empty:
        base_result["extra"]["result_status"] = "no_valid_scores"
        return base_result

    missing_identity_indexes = [
        row_index
        for row_index in valid_scores.index
        if row_index not in identity_records_by_index
    ]
    if missing_identity_indexes:
        raise ValueError("当前考试档案的学生身份映射不完整。")
    subject_score_mapping = bind_subject_scores_by_row_index(
        valid_scores,
        identity_records_by_index,
    )
    subject_analysis_result = analyze_scores(
        subject_score_mapping,
        full_score=full_score,
        excellent_percent=excellent_percent,
        current_class="全部学生",
        current_subject=score_col,
    )
    metric_names = (
        "student_count",
        "average_score",
        "highest_score",
        "lowest_score",
        "pass_rate",
        "excellent_rate",
    )
    base_result["metrics"] = {
        name: deepcopy(subject_analysis_result[name])
        for name in metric_names
        if name in subject_analysis_result
    }
    for table_name in (
        "score_details",
        "excellent_students",
        "fail_students",
    ):
        base_result["tables"][table_name] = deepcopy(
            subject_analysis_result.get(table_name, [])
        )
    base_result["extra"]["legacy_analysis_result"] = deepcopy(
        subject_analysis_result
    )
    base_result["extra"]["result_status"] = "ready"

    if class_col is None:
        base_result["extra"]["comparison_status"] = "missing_class_column"
        return base_result
    if len(selected_classes) < 2:
        base_result["extra"]["comparison_status"] = "not_enough_classes"
        return base_result

    comparison = build_subject_analysis_comparison(
        subject_rows,
        class_col=class_col,
        name_col=name_col,
        score_col=score_col,
        selected_classes=selected_classes,
        full_score=full_score,
        excellent_percent=excellent_percent,
    )
    base_result["tables"]["class_comparison"] = comparison.summary
    base_result["tables"]["comparison_levels"] = comparison.levels
    base_result["tables"]["comparison_excluded"] = comparison.excluded
    base_result["charts"]["class_average_rate_data"] = comparison.summary
    base_result["charts"]["level_structure_data"] = comparison.levels
    base_result["extra"]["comparison_status"] = (
        "comparable" if comparison.is_comparable else "not_comparable"
    )
    return base_result


def render_structured_subject_result(result, *, score_col):
    """使用缓存中的结构化数据调用现有组件和图表函数。"""

    if result is None or not isinstance(result.payload, ResultPayload):
        raise TypeError("学科分析结果必须使用结构化 ResultPayload。")
    payload = result.payload
    invalid_warning = payload.extra.get("invalid_warning")
    if invalid_warning:
        st.warning(invalid_warning)
    if payload.extra.get("result_status") == "no_valid_scores":
        st.info("当前科目没有可用于分析的有效成绩。")
        return

    legacy_analysis_result = payload.extra.get("legacy_analysis_result")
    if not isinstance(legacy_analysis_result, dict):
        raise TypeError("学科分析结果缺少兼容指标数据。")
    render_anchor("section-subject-metrics")
    with st.container(border=True):
        render_section_header("学科指标", "统", f"当前科目：{score_col}")
        render_metric_grid(legacy_analysis_result)

    render_anchor("section-subject-class-comparison")
    with st.container(border=True):
        render_section_header(
            "班级对比",
            "比",
            "对比当前学科在各班的平均得分率。",
        )
        comparison_status = payload.extra.get("comparison_status")
        if comparison_status == "missing_class_column":
            st.info("当前考试未识别到班级列，暂无法生成班级对比图。")
            return
        if comparison_status == "not_enough_classes":
            st.info("当前考试不足两个有效班级，暂无法生成班级对比图。")
            return

        excluded = payload.tables.get("comparison_excluded")
        if isinstance(excluded, pd.DataFrame) and not excluded.empty:
            st.warning("部分班级没有有效成绩，已从学科班级对比图中排除。")
        if comparison_status != "comparable":
            st.info("排除无有效成绩的班级后，可比较班级不足两个。")
            return

        summary = payload.charts.get("class_average_rate_data")
        levels = payload.charts.get("level_structure_data")
        if not isinstance(summary, pd.DataFrame) or not isinstance(
            levels,
            pd.DataFrame,
        ):
            raise TypeError("学科分析缓存缺少图表数据。")
        chart_config = {"displayModeBar": False, "displaylogo": False}
        average_rate_figure = build_average_rate_figure(summary)
        style_dashboard_figure(
            average_rate_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            average_rate_figure,
            width="stretch",
            config=chart_config,
        )

        render_anchor("section-subject-level-structure")
        level_structure_figure = build_level_structure_figure(levels)
        style_dashboard_figure(
            level_structure_figure,
            height=420,
            preserve_trace_colors=True,
        )
        st.plotly_chart(
            level_structure_figure,
            width="stretch",
            config=chart_config,
        )


def render_structured_subject_analysis_page(
    snapshot,
    *,
    exam_context,
    exam_config,
    current_page_state,
    result_store,
):
    """以 PageState 和 ResultStore 驱动学科分析，不写入考试规则。"""

    identity_records_by_index = exam_context.identity_records_by_index
    subject_scores_by_index = exam_context.subject_scores_by_index
    score_options = list(exam_context.schema.score_columns)
    if not identity_records_by_index:
        raise ValueError("当前考试快照缺少学生身份映射。")
    if not subject_scores_by_index or not score_options:
        raise ValueError("当前考试快照缺少可用于学科分析的数据。")

    page_subject = (
        current_page_state.selected_subject
        if current_page_state.exam_id == exam_context.exam_id
        else None
    )
    preferred_score_col = resolve_column_selection(
        score_options,
        st.session_state.get("subject_analysis_score_column"),
        page_subject or (score_options[0] if score_options else None),
    )
    if st.session_state.get("subject_analysis_score_column") != preferred_score_col:
        st.session_state["subject_analysis_score_column"] = preferred_score_col

    with st.container(border=True):
        render_section_header(
            "学科分析设置",
            "设",
            "页面调整仅用于本次查看，不修改考试默认评价规则。",
        )
        settings_columns = st.columns(4)
        score_col = settings_columns[0].selectbox(
            "分析科目",
            score_options,
            key="subject_analysis_score_column",
        )
        cleaned_score_col = clean_column_name(score_col)
        existing_overrides = (
            deepcopy(dict(current_page_state.config_overrides))
            if current_page_state.exam_id == exam_context.exam_id
            else {}
        )
        provisional_page_state = replace(
            current_page_state,
            exam_id=exam_context.exam_id,
            page_name="subject_analysis",
            selected_subject=score_col,
            selected_classes=(),
            config_overrides=existing_overrides,
        )
        snapshot_full_scores = snapshot.get("full_score_by_column") or {}
        system_default = SubjectConfig(
            full_score=float(
                snapshot_full_scores.get(
                    cleaned_score_col,
                    get_full_score_suggestion(score_col).value,
                )
            ),
            excellent_percent=90.0,
            pass_percent=60.0,
        )
        resolved_config = effective_config(
            exam_config,
            provisional_page_state,
            score_col,
            system_default,
        )
        context_key = snapshot.get("score_context_key", exam_context.exam_id)
        full_score_widget_key = (
            f"subject_analysis::full_score::{context_key}::{cleaned_score_col}"
        )
        excellent_widget_key = (
            f"subject_analysis::excellent_percent::{context_key}::{cleaned_score_col}"
        )
        if full_score_widget_key not in st.session_state:
            st.session_state[full_score_widget_key] = float(
                resolved_config.full_score
            )
        if excellent_widget_key not in st.session_state:
            st.session_state[excellent_widget_key] = float(
                resolved_config.excellent_percent
            )
        full_score = settings_columns[1].number_input(
            "满分",
            min_value=1.0,
            step=1.0,
            key=full_score_widget_key,
        )
        with settings_columns[2]:
            st.metric("及格线", "60%", help="及格线固定为满分的60%，当前不可编辑。")
        excellent_percent = settings_columns[3].number_input(
            "优秀线（%）",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=excellent_widget_key,
        )

    effective_excellent_percent = normalize_excellent_percent(excellent_percent)
    if excellent_percent < 60:
        st.warning("优秀线不能低于及格线60%，本次学科分析将按60%处理。")
    class_col = exam_context.schema.class_column
    selected_classes = (
        natural_sort_class_names(
            record.get("班级") for record in identity_records_by_index.values()
        )
        if class_col is not None
        else []
    )
    subject_overrides = deepcopy(existing_overrides)
    subject_overrides[cleaned_score_col] = {
        "full_score": float(full_score),
        "excellent_percent": float(excellent_percent),
    }
    subject_page_state = replace(
        provisional_page_state,
        selected_classes=tuple(selected_classes),
        config_overrides=subject_overrides,
    )
    st.session_state["current_page_state"] = subject_page_state

    result = get_or_build_subject_result(
        exam_context,
        exam_config,
        subject_page_state,
        result_store,
        lambda: calculate_subject_analysis_payload(
            exam_context,
            score_col=score_col,
            selected_classes=selected_classes,
            full_score=float(full_score),
            excellent_percent=effective_excellent_percent,
        ),
    )
    if result is None:
        return False
    render_structured_subject_result(result, score_col=score_col)
    return True


def render_class_analysis_page(snapshot):
    identity_records_by_index = snapshot.get("identity_records_by_index")
    subject_scores_by_index = snapshot.get("subject_scores_by_index")
    score_options = list(snapshot.get("score_options") or [])
    class_col = snapshot.get("class_col")
    if not identity_records_by_index:
        st.error("当前考试快照缺少学生身份映射，请返回年级总览重新完成分析。")
        return
    if not subject_scores_by_index or not score_options:
        st.error("当前考试快照缺少可用于班级分析的学科成绩，请返回年级总览重新完成分析。")
        return
    if class_col is None:
        st.info("当前考试未识别到班级列，暂无法进行班级分析。")
        return

    preferred_score_col = initialize_class_analysis_state(
        st.session_state,
        snapshot,
    )
    try:
        initial_dataframe = build_class_analysis_dataframe(
            snapshot,
            preferred_score_col,
        )
    except ValueError as exc:
        st.error(f"准备班级分析数据失败：{exc}")
        return

    class_options = natural_sort_class_names(initial_dataframe[class_col])
    if len(class_options) < 2:
        st.info("当前考试不足两个有效班级，暂无法进行班级对比。")
        return
    if "class_analysis_classes" not in st.session_state:
        st.session_state["class_analysis_classes"] = class_options[:6]
    else:
        stored_classes = st.session_state.get("class_analysis_classes") or []
        valid_classes = [
            class_name
            for class_name in stored_classes
            if class_name in class_options
        ]
        if valid_classes != stored_classes:
            st.session_state["class_analysis_classes"] = valid_classes

    with st.container(border=True):
        render_section_header(
            "班级分析设置",
            "设",
            "仅调整班级分析页面，不修改年级总览的成绩列、满分、优秀线或班级范围。",
        )
        setting_columns = st.columns(3)
        score_col = setting_columns[0].selectbox(
            "科目",
            score_options,
            key="class_analysis_score_column",
            on_change=reset_class_analysis_full_score,
            args=(snapshot,),
        )
        full_score = setting_columns[1].number_input(
            "满分",
            min_value=1.0,
            step=1.0,
            key="class_analysis_full_score",
        )
        excellent_percent = setting_columns[2].number_input(
            "优秀线（%）",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key="class_analysis_excellent_percent",
        )
        st.metric("及格线", "60%", help="及格线固定为满分的60%，当前不可编辑。")
        selected_classes = st.multiselect(
            "选择对比班级",
            class_options,
            key="class_analysis_classes",
        )

    effective_excellent_percent = normalize_excellent_percent(excellent_percent)
    if excellent_percent < 60:
        st.warning("优秀线不能低于及格线60%，本次班级分析将按60%处理。")
    try:
        _, result = build_class_analysis_comparison(
            snapshot,
            score_col=score_col,
            selected_classes=selected_classes,
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
        )
    except ValueError as exc:
        st.error(f"生成班级分析失败：{exc}")
        return

    render_class_comparison_section(
        result=result,
        score_col=score_col,
        full_score=full_score,
        excellent_percent=effective_excellent_percent,
        selected_classes=selected_classes,
    )


CLASS_ANALYSIS_OVERRIDE_NAMESPACE = "__class_analysis__"


def read_class_analysis_overrides(page_state, exam_id):
    """读取班级页面命名空间内的临时规则，并返回独立副本。"""

    if page_state.exam_id != exam_id:
        return {}
    scoped_overrides = page_state.config_overrides.get(
        CLASS_ANALYSIS_OVERRIDE_NAMESPACE
    )
    if isinstance(scoped_overrides, dict):
        return deepcopy(scoped_overrides)
    if page_state.page_name == "class_comparison":
        return deepcopy(dict(page_state.config_overrides))
    return {}


def calculate_class_analysis_payload(
    exam_context,
    *,
    score_col,
    selected_classes,
    full_score,
    excellent_percent,
):
    """按原始行索引调用现有班级比较计算，并返回无 figure 的结果字典。"""

    identity_records_by_index = exam_context.identity_records_by_index
    subject_scores_by_index = exam_context.subject_scores_by_index
    name_col = exam_context.schema.name_column
    class_col = exam_context.schema.class_column
    if not identity_records_by_index:
        raise ValueError("当前考试档案缺少学生身份映射。")
    if not subject_scores_by_index:
        raise ValueError("当前考试档案缺少学科成绩数据。")
    if class_col is None:
        raise ValueError("当前考试未识别到班级列。")

    row_indexes = []
    row_records = []
    for row_index, identity_record in identity_records_by_index.items():
        row_scores = subject_scores_by_index.get(row_index)
        if row_scores is None or score_col not in row_scores:
            raise ValueError("学生身份与学科成绩无法按原始行索引对应。")
        row_indexes.append(row_index)
        row_records.append(
            {
                class_col: identity_record["班级"],
                name_col: identity_record["姓名"],
                score_col: row_scores[score_col],
            }
        )
    dataframe = pd.DataFrame(row_records, index=row_indexes)
    comparison = build_class_comparison(
        dataframe,
        class_column=class_col,
        name_column=name_col,
        score_column=score_col,
        selected_classes=selected_classes,
        full_score=full_score,
        excellent_percent=excellent_percent,
    )
    class_metrics = comparison.summary.to_dict("records")
    student_count = (
        int(comparison.summary["有效人数"].sum())
        if "有效人数" in comparison.summary
        else 0
    )
    return {
        "summary": {
            "current_subject": score_col,
            "selected_classes": tuple(selected_classes),
            "analysis_scope": "班级对比",
        },
        "metrics": {
            "class_count": len(comparison.summary),
            "student_count": student_count,
            "class_metrics": class_metrics,
        },
        "tables": {
            "class_comparison": comparison.summary,
            "level_structure": comparison.levels,
            "excluded_classes": comparison.excluded,
        },
        "charts": {
            "average_rate_data": comparison.summary,
            "pass_excellent_data": comparison.summary,
            "level_structure_data": comparison.levels,
        },
        "extra": {},
    }


def render_structured_class_result(
    result,
    *,
    score_col,
    full_score,
    excellent_percent,
    selected_classes,
):
    """从结构化缓存恢复比较数据，并复用现有班级结果渲染。"""

    if result is None or not isinstance(result.payload, ResultPayload):
        raise TypeError("班级分析结果必须使用结构化 ResultPayload。")
    summary = result.payload.tables.get("class_comparison")
    levels = result.payload.tables.get("level_structure")
    excluded = result.payload.tables.get("excluded_classes")
    if not all(
        isinstance(dataframe, pd.DataFrame)
        for dataframe in (summary, levels, excluded)
    ):
        raise TypeError("班级分析缓存缺少比较表或等级结构数据。")
    comparison = ClassComparisonResult(
        summary=summary,
        levels=levels,
        excluded=excluded,
    )
    render_class_comparison_section(
        result=comparison,
        score_col=score_col,
        full_score=full_score,
        excellent_percent=excellent_percent,
        selected_classes=selected_classes,
    )


def render_structured_class_analysis_page(
    *,
    exam_context,
    exam_config,
    current_page_state,
    result_store,
):
    """以班级 PageState 和 ResultStore 驱动班级分析。"""

    identity_records_by_index = exam_context.identity_records_by_index
    subject_scores_by_index = exam_context.subject_scores_by_index
    score_options = list(exam_context.schema.score_columns)
    class_col = exam_context.schema.class_column
    if not identity_records_by_index:
        raise ValueError("当前考试档案缺少学生身份映射。")
    if not subject_scores_by_index or not score_options:
        raise ValueError("当前考试档案缺少可用于班级分析的成绩。")
    if class_col is None:
        raise ValueError("当前考试未识别到班级列。")

    page_matches_class_analysis = (
        current_page_state.exam_id == exam_context.exam_id
        and current_page_state.page_name == "class_comparison"
    )
    page_subject = (
        current_page_state.selected_subject
        if page_matches_class_analysis
        else None
    )
    preferred_score_col = resolve_column_selection(
        score_options,
        st.session_state.get("class_analysis_score_column"),
        page_subject or score_options[0],
    )
    if st.session_state.get("class_analysis_score_column") != preferred_score_col:
        st.session_state["class_analysis_score_column"] = preferred_score_col

    class_options = natural_sort_class_names(
        record.get("班级") for record in identity_records_by_index.values()
    )
    if len(class_options) < 2:
        st.info("当前考试不足两个有效班级，暂无法进行班级对比。")
        return True

    existing_overrides = read_class_analysis_overrides(
        current_page_state,
        exam_context.exam_id,
    )
    provisional_page_state = replace(
        current_page_state,
        exam_id=exam_context.exam_id,
        page_name="class_comparison",
        selected_subject=preferred_score_col,
        selected_classes=(),
        config_overrides=existing_overrides,
    )
    system_default = SubjectConfig(
        full_score=float(get_full_score_suggestion(preferred_score_col).value),
        excellent_percent=90.0,
        pass_percent=60.0,
    )
    resolved_config = effective_config(
        exam_config,
        provisional_page_state,
        preferred_score_col,
        system_default,
    )
    cleaned_score_col = clean_column_name(preferred_score_col)
    full_score_widget_key = (
        f"class_analysis::full_score::{exam_context.exam_id}::{cleaned_score_col}"
    )
    excellent_widget_key = (
        f"class_analysis::excellent_percent::{exam_context.exam_id}::{cleaned_score_col}"
    )
    classes_widget_key = (
        f"class_analysis::classes::{exam_context.exam_id}::{cleaned_score_col}"
    )
    if full_score_widget_key not in st.session_state:
        st.session_state[full_score_widget_key] = float(resolved_config.full_score)
    if excellent_widget_key not in st.session_state:
        st.session_state[excellent_widget_key] = float(
            resolved_config.excellent_percent
        )
    if classes_widget_key not in st.session_state:
        stored_classes = (
            current_page_state.selected_classes
            if page_matches_class_analysis
            else ()
        )
        valid_stored_classes = [
            class_name
            for class_name in stored_classes
            if class_name in class_options
        ]
        st.session_state[classes_widget_key] = (
            valid_stored_classes or class_options[:6]
        )

    with st.container(border=True):
        render_section_header(
            "班级分析设置",
            "设",
            "页面调整仅用于本次班级对比，不修改考试默认评价规则。",
        )
        setting_columns = st.columns(3)
        score_col = setting_columns[0].selectbox(
            "科目",
            score_options,
            key="class_analysis_score_column",
        )
        full_score = setting_columns[1].number_input(
            "满分",
            min_value=1.0,
            step=1.0,
            key=full_score_widget_key,
        )
        excellent_percent = setting_columns[2].number_input(
            "优秀线（%）",
            min_value=0.0,
            max_value=100.0,
            step=1.0,
            key=excellent_widget_key,
        )
        st.metric("及格线", "60%", help="及格线固定为满分的60%，当前不可编辑。")
        selected_classes = st.multiselect(
            "选择对比班级",
            class_options,
            key=classes_widget_key,
        )

    effective_excellent_percent = normalize_excellent_percent(excellent_percent)
    if excellent_percent < 60:
        st.warning("优秀线不能低于及格线60%，本次班级分析将按60%处理。")
    class_overrides = deepcopy(existing_overrides)
    class_overrides[clean_column_name(score_col)] = {
        "full_score": float(full_score),
        "excellent_percent": float(excellent_percent),
    }
    class_page_state = replace(
        provisional_page_state,
        selected_subject=score_col,
        selected_classes=tuple(selected_classes),
        config_overrides=class_overrides,
    )
    stored_class_page_state = replace(
        class_page_state,
        config_overrides={CLASS_ANALYSIS_OVERRIDE_NAMESPACE: class_overrides},
    )
    st.session_state["current_page_state"] = stored_class_page_state

    result = get_or_build_class_result(
        exam_context,
        exam_config,
        class_page_state,
        result_store,
        lambda: calculate_class_analysis_payload(
            exam_context,
            score_col=score_col,
            selected_classes=selected_classes,
            full_score=float(full_score),
            excellent_percent=effective_excellent_percent,
        ),
    )
    if result is None:
        return False
    render_structured_class_result(
        result,
        score_col=score_col,
        full_score=full_score,
        excellent_percent=effective_excellent_percent,
        selected_classes=selected_classes,
    )
    return True


if analysis_mode == "subject_analysis":
    snapshot = st.session_state.get("current_exam_snapshot")
    if not snapshot:
        with sidebar_context:
            render_current_context("等待完成成绩分析")
        st.info("请先上传成绩表并完成年级总览，再进入学科分析。")
        st.stop()
    with sidebar_context:
        render_current_context(
            f'学科分析 · {st.session_state.get("subject_analysis_score_column", snapshot["score_col"])}'
        )
    rendered_with_new_architecture = False
    current_exam_context = st.session_state.get("current_exam_context")
    current_exam_config = st.session_state.get("current_exam_config")
    current_page_state = st.session_state.get("current_page_state")
    result_store = st.session_state.get("result_store")
    if (
        current_exam_context is not None
        and current_exam_config is not None
        and isinstance(current_page_state, PageState)
    ):
        if not isinstance(result_store, ResultStore):
            result_store = ResultStore()
            st.session_state["result_store"] = result_store
        try:
            rendered_with_new_architecture = (
                render_structured_subject_analysis_page(
                    snapshot,
                    exam_context=current_exam_context,
                    exam_config=current_exam_config,
                    current_page_state=current_page_state,
                    result_store=result_store,
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            rendered_with_new_architecture = False
    if not rendered_with_new_architecture:
        render_subject_analysis_page(snapshot)
    st.stop()


if analysis_mode == "class_comparison":
    snapshot = st.session_state.get("current_exam_snapshot")
    if not snapshot:
        with sidebar_context:
            render_current_context("等待完成成绩分析")
        st.info("请先上传成绩表并完成年级总览，再进入班级分析。")
        st.stop()
    with sidebar_context:
        render_current_context(
            f'班级分析 · {st.session_state.get("class_analysis_score_column", snapshot["score_col"])}'
        )
    rendered_with_new_architecture = False
    current_exam_context = st.session_state.get("current_exam_context")
    current_exam_config = st.session_state.get("current_exam_config")
    current_page_state = st.session_state.get("current_page_state")
    result_store = st.session_state.get("result_store")
    if (
        current_exam_context is not None
        and current_exam_config is not None
        and isinstance(current_page_state, PageState)
    ):
        if not isinstance(result_store, ResultStore):
            result_store = ResultStore()
            st.session_state["result_store"] = result_store
        try:
            rendered_with_new_architecture = (
                render_structured_class_analysis_page(
                    exam_context=current_exam_context,
                    exam_config=current_exam_config,
                    current_page_state=current_page_state,
                    result_store=result_store,
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            rendered_with_new_architecture = False
    if not rendered_with_new_architecture:
        render_class_analysis_page(snapshot)
    st.stop()


uploaded_file = None
selected_sheet = None
cached_file_bytes = st.session_state.get("current_exam_file_bytes")
show_upload = analysis_mode == "single_class" or not cached_file_bytes

if show_upload:
    render_anchor("data-import")
    with st.container(border=True):
        render_section_header(
            "上传并开始分析",
            "入",
            "依次完成 Excel 上传、工作表选择和字段确认，分析结果会自动显示在下方。",
        )
        uploaded_file = st.file_uploader(
            "上传 Excel 成绩表",
            type=["xlsx", "xls"],
        )
        st.markdown(
            '<p class="section-note">已有成绩表可直接上传；没有表格？可下载单科成绩模板。</p>',
            unsafe_allow_html=True,
        )
        st.download_button(
            "下载单科成绩模板",
            data=create_single_score_template(),
            file_name="单科成绩模板.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    uploaded_file = restore_current_exam_file(st.session_state)

if uploaded_file:
    try:
        uploaded_file.seek(0)
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_names = excel_file.sheet_names
        preferred_sheet = resolve_column_selection(
            sheet_names,
            st.session_state.get("analysis_sheet"),
            sheet_names[0],
        )
        if st.session_state.get("analysis_sheet") != preferred_sheet:
            st.session_state["analysis_sheet"] = preferred_sheet
        selected_sheet = preferred_sheet
    except Exception as e:
        st.error(f"读取 Excel 工作表失败：{e}")
        st.stop()


if uploaded_file:
    try:
        uploaded_file.seek(0)
        raw_df = pd.read_excel(uploaded_file, sheet_name=selected_sheet, header=None)

        if raw_df.empty:
            st.error("当前工作表未识别到可分析的成绩数据，请选择其他工作表。")
            st.stop()

        detected_header_row = detect_header_row(raw_df)
        default_header_row = detected_header_row + 1 if detected_header_row is not None else 1

        with st.container(border=True):
            render_section_header("表头设置", "表")
            if detected_header_row is not None:
                st.success(f"已自动识别第 {default_header_row} 行为表头。")
            else:
                st.warning("没有自动识别到表头，请手动选择表头所在 Excel 行号。")

            header_row_number = st.number_input(
                "表头所在 Excel 行号",
                min_value=1,
                max_value=int(len(raw_df)),
                value=int(default_header_row),
                step=1,
            )

        df = build_dataframe_from_header(raw_df, int(header_row_number) - 1)

        with st.container(border=True):
            render_section_header("原始成绩预览", "览", "用于核对表头与字段，原始 Excel 不会被修改。")
            st.dataframe(df, width="stretch", height=280)

        if df.empty:
            st.error("表头下方没有可分析的数据。")
            st.stop()
        if len(df.columns) < 2:
            st.error("Excel 至少需要两列数据，才能分别选择姓名列和成绩列。")
            st.stop()

        columns = df.columns.tolist()
        if not has_analyzable_columns(columns):
            st.error("当前工作表未识别到可分析的成绩数据，请选择其他工作表。")
            st.stop()

        matched_name_col = find_first_matching_column(columns, NAME_COLUMN_ALIASES)
        matched_score_col = find_first_matching_score_column(columns)
        matched_class_col = find_first_matching_column(columns, CLASS_COLUMN_ALIASES)
        student_id_col = find_student_id_column(columns)

        preferred_name_col = resolve_column_selection(
            columns,
            st.session_state.get("analysis_name_column"),
            matched_name_col,
            fallback_index=0,
        )
        if st.session_state.get("analysis_name_column") != preferred_name_col:
            st.session_state["analysis_name_column"] = preferred_name_col

        class_col = None
        if matched_class_col is not None:
            preferred_class_col = resolve_column_selection(
                columns,
                st.session_state.get("analysis_class_column"),
                matched_class_col,
                fallback_index=0,
            )
            if st.session_state.get("analysis_class_column") != preferred_class_col:
                st.session_state["analysis_class_column"] = preferred_class_col

        with st.container(border=True):
            render_section_header(
                "字段识别",
                "识",
                "确认姓名列和班级列；分析条件统一在下方“分析设置”中调整。",
            )
            name_col = st.selectbox(
                "姓名列",
                columns,
                key="analysis_name_column",
            )
            if matched_class_col is not None:
                class_col = st.selectbox(
                    "班级列",
                    columns,
                    key="analysis_class_column",
                )
            else:
                st.info("当前工作表未识别到班级列，将整张表作为“全部学生”进行分析。")

        score_options = build_score_column_options(
            columns,
            excluded_columns=(name_col, class_col, student_id_col),
        )
        if not score_options:
            st.error("当前工作表没有可用的科目或成绩列。")
            st.stop()
        preferred_score_col = resolve_column_selection(
            score_options,
            st.session_state.get("analysis_score_column"),
            matched_score_col,
            fallback_index=0,
        )
        if st.session_state.get("analysis_score_column") != preferred_score_col:
            st.session_state["analysis_score_column"] = preferred_score_col

        exam_import_file_content = uploaded_file.getvalue()
        exam_import_file_name = getattr(
            uploaded_file,
            "name",
            "当前考试.xlsx",
        )
        exam_column_mapping = ExamColumnMapping(
            name_column=name_col,
            class_column=class_col,
            student_id_column=student_id_col,
            score_columns=tuple(score_options),
        )
        current_exam_context = ensure_current_exam_context(
            st.session_state,
            service=ExamImportService(),
            file_content=exam_import_file_content,
            file_name=exam_import_file_name,
            sheet_names=sheet_names,
            sheet_name=selected_sheet,
            detected_header_row=detected_header_row,
            header_row_index=int(header_row_number) - 1,
            dataframe=df,
            column_mapping=exam_column_mapping,
            exam_name=Path(exam_import_file_name).stem,
        )

        grade_overview_dataframe, grade_overview_context = (
            resolve_grade_overview_fact_source(df, current_exam_context)
        )
        if grade_overview_context is not None:
            name_col = grade_overview_context.schema.name_column
            class_col = grade_overview_context.schema.class_column
            student_id_col = grade_overview_context.schema.student_id_column
            score_options = list(grade_overview_context.schema.score_columns)

        class_options = (
            build_single_class_options(grade_overview_dataframe[class_col])
            if class_col is not None
            else []
        )
        selected_class = resolve_single_class_selection(
            class_options,
            st.session_state.get("selected_class"),
        )

        with st.container(border=True):
            render_section_header("分析设置", "设", "选择当前分析范围与评价标准。")
            top_columns = st.columns(
                3 if workflow_mode == "single_class" and class_col is not None else 2
            )
            selected_sheet = top_columns[0].selectbox(
                "工作表",
                sheet_names,
                key="analysis_sheet",
            )
            score_col = top_columns[1].selectbox(
                "科目 / 成绩列",
                score_options,
                key="analysis_score_column",
            )

            if workflow_mode == "single_class" and class_col is not None and class_options:
                preferred_single_class = resolve_single_class_selection(
                    class_options,
                    st.session_state.get("selected_class"),
                )
                if st.session_state.get("analysis_single_class") not in class_options:
                    st.session_state["analysis_single_class"] = preferred_single_class
                selected_class = top_columns[2].selectbox(
                    "当前班级",
                    class_options,
                    key="analysis_single_class",
                )
                st.session_state["selected_class"] = selected_class
            elif class_col is None:
                selected_class = "全部学生"
                st.session_state["selected_class"] = selected_class
                st.session_state["analysis_single_class"] = "全部学生"

            score_context_key = build_full_score_context_key(
                uploaded_file.getvalue(),
                selected_sheet,
            )
            full_score_settings = st.session_state.setdefault("full_score_by_context", {})
            snapshot = st.session_state.get("current_exam_snapshot") or {}
            cached_full_score = None
            if snapshot.get("score_context_key") == score_context_key:
                cached_full_score = (snapshot.get("full_score_by_column") or {}).get(
                    clean_column_name(score_col)
                )
            standard_columns = st.columns(3)
            system_default = SubjectConfig(
                full_score=float(get_full_score_suggestion(score_col).value),
                excellent_percent=90.0,
                pass_percent=60.0,
            )
            grade_overview_rule_source = resolve_grade_overview_rule_source(
                grade_overview_context,
                st.session_state.get("current_exam_config"),
                st.session_state.get("current_page_state"),
                score_col,
                selected_class,
                system_default,
            )
            grade_overview_page_state = None
            if grade_overview_rule_source is not None:
                (
                    base_grade_config,
                    resolved_grade_config,
                    provisional_grade_page_state,
                    existing_grade_overrides,
                    reset_grade_widgets,
                ) = grade_overview_rule_source
                full_score_key = build_full_score_widget_key(
                    score_context_key,
                    score_col,
                )
                if reset_grade_widgets:
                    st.session_state[full_score_key] = float(
                        resolved_grade_config.full_score
                    )
                    st.session_state["analysis_excellent_percent"] = float(
                        resolved_grade_config.excellent_percent
                    )
                else:
                    safe_full_score, _ = sanitize_grade_overview_widget_rules(
                        st.session_state.get(full_score_key),
                        resolved_grade_config.excellent_percent,
                        resolved_grade_config,
                    )
                    _, safe_excellent_percent = sanitize_grade_overview_widget_rules(
                        resolved_grade_config.full_score,
                        st.session_state.get("analysis_excellent_percent"),
                        resolved_grade_config,
                    )
                    st.session_state[full_score_key] = safe_full_score
                    st.session_state[
                        "analysis_excellent_percent"
                    ] = safe_excellent_percent
                widget_full_score = standard_columns[0].number_input(
                    "当前成绩列满分",
                    min_value=1.0,
                    step=1.0,
                    key=full_score_key,
                )
                st.session_state["analysis_pass_percent"] = float(
                    resolved_grade_config.pass_percent
                )
                standard_columns[1].number_input(
                    "及格线（固定，%）",
                    step=1.0,
                    disabled=True,
                    key="analysis_pass_percent",
                )
                excellent_percent = standard_columns[2].number_input(
                    "优秀线（%）",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="analysis_excellent_percent",
                )
                full_score, excellent_percent = (
                    sanitize_grade_overview_widget_rules(
                        widget_full_score,
                        excellent_percent,
                        resolved_grade_config,
                    )
                )
                grade_overview_page_state = update_grade_overview_page_state(
                    provisional_grade_page_state,
                    existing_grade_overrides,
                    subject=score_col,
                    selected_class=selected_class,
                    full_score=full_score,
                    excellent_percent=excellent_percent,
                    base_config=base_grade_config,
                )
                st.session_state[
                    "current_page_state"
                ] = grade_overview_page_state
            else:
                full_score_key, _ = initialize_full_score_widget_state(
                    st.session_state,
                    full_score_settings,
                    score_context_key,
                    score_col,
                    cached_full_score,
                )
                widget_full_score = standard_columns[0].number_input(
                    "当前成绩列满分",
                    min_value=1.0,
                    step=1.0,
                    key=full_score_key,
                )
                full_score = set_column_full_score_safely(
                    full_score_settings,
                    score_context_key,
                    score_col,
                    widget_full_score,
                    cached_full_score,
                )
                st.session_state.setdefault("analysis_pass_percent", 60.0)
                standard_columns[1].number_input(
                    "及格线（固定，%）",
                    step=1.0,
                    disabled=True,
                    key="analysis_pass_percent",
                )
                st.session_state.setdefault("analysis_excellent_percent", 90.0)
                excellent_percent = standard_columns[2].number_input(
                    "优秀线（%）",
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="analysis_excellent_percent",
                )
            full_score_suggestion = get_full_score_suggestion(score_col)
            if full_score_suggestion.requires_confirmation:
                st.warning(
                    "自动建议的满分超出 10–1000 分安全范围，"
                    "当前使用 100 分作为占位，请确认并手动调整。"
                )

        effective_excellent_percent = normalize_excellent_percent(excellent_percent)
        if excellent_percent < 60:
            st.warning("优秀线不能低于及格线 60%，本次分析将按 60% 处理。")
        total_score_notice = get_total_score_notice(score_col)
        if total_score_notice:
            st.info(total_score_notice)

        summary_class = (
            selected_class
            if class_options or class_col is None
            else "未识别有效班级"
        )

        with sidebar_context:
            render_current_context(f"{summary_class} · {score_col}")

        if workflow_mode == "single_class" and class_col is not None and not class_options:
            st.info("当前班级列没有识别到有效班级，暂无法进行单班成绩分析。")
            st.stop()

        if name_col == score_col:
            st.error("请选择不同的姓名列和分析科目 / 成绩列。")
            st.stop()

        analysis_df = filter_dataframe_by_class(
            grade_overview_dataframe,
            class_col,
            selected_class,
        )

        selected_columns = [name_col, score_col]
        if class_col is not None and class_col not in selected_columns:
            selected_columns.insert(0, class_col)
        if student_id_col is not None and student_id_col not in selected_columns:
            selected_columns.insert(0, student_id_col)

        selected = analysis_df[selected_columns].copy()
        if class_col is not None:
            selected[class_col] = selected[class_col].apply(format_class_value)

        classified_rows = classify_score_rows(
            selected[name_col],
            selected[score_col],
            full_score=full_score,
        )
        selected["姓名"] = classified_rows["姓名"]
        selected["分数"] = classified_rows["分数"]
        selected["无效原因"] = classified_rows["无效原因"]
        valid_scores = selected[selected["无效原因"].isna()].copy()

        invalid_reason_counts = count_invalid_reasons(classified_rows)
        invalid_warning = build_invalid_data_warning(invalid_reason_counts, full_score)
        if invalid_warning:
            st.warning(invalid_warning)

        if valid_scores.empty:
            with st.container(border=True):
                render_section_header("成绩可视化分析", "图")
                st.info("当前筛选条件下没有可用于分析的有效成绩。")
            st.stop()

        identity_records = prepare_grade_overview_identity_records(
            grade_overview_context,
            valid_scores,
            score_col=score_col,
            class_col=class_col,
            student_id_col=student_id_col,
        )
        identity_analysis_result = analyze_scores(
            build_student_score_mapping(identity_records),
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
            current_class=selected_class,
            current_subject=score_col,
        )
        display_score_details = build_display_score_details(
            identity_analysis_result,
            identity_records,
        )
        analysis_result = restore_analysis_result_display_names(
            identity_analysis_result,
            identity_records,
        )
        export_analysis_result = restore_analysis_result_display_names(
            identity_analysis_result,
            identity_records,
            contextualize_duplicate_names=True,
        )

        if analysis_mode == "single_class":
            cache_current_exam(st.session_state, uploaded_file)
            activate_analysis_center(st.session_state)
            st.rerun()

        if analysis_mode == "analysis_center":
            exam_student_count = count_exam_students(
                grade_overview_dataframe,
                name_column=name_col,
                class_column=class_col,
                student_id_column=student_id_col,
            )
            exam_class_count = count_exam_classes(
                class_options,
                has_class_column=class_col is not None,
            )
            exam_name = st.session_state.get("word_report_exam_name") or Path(
                st.session_state.get("current_exam_file_name", "本次考试")
            ).stem
            with analysis_center_slot.container():
                render_analysis_center_top(st.session_state)
                render_exam_analysis_center(
                    exam_name=exam_name,
                    exam_time=st.session_state.get("current_exam_time", "未设置"),
                    student_count=exam_student_count,
                    class_count=exam_class_count,
                    subject=score_col,
                    data_status="已就绪",
                )

        render_anchor("section-overview")
        with st.container(border=True):
            scope_caption = (
                f"当前范围：全部学生 · 科目：{score_col}"
                if selected_class == "全部学生"
                else f"当前班级：{selected_class} · 科目：{score_col}"
            )
            render_section_header("核心统计", "统", scope_caption)
            render_metric_grid(analysis_result)

        distribution = calculate_score_distribution(
            valid_scores["分数"],
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
        )
        valid_names = analysis_df[name_col].astype(str).str.replace("\u3000", "", regex=False).str.strip()
        subject_source = analysis_df[
            (valid_names != "") & (valid_names.str.lower() != "nan")
        ].copy()
        subject_averages = calculate_subject_averages(subject_source)
        distribution_figure = build_distribution_figure(distribution)
        level_figure = build_level_donut_figure(distribution)
        style_dashboard_figure(distribution_figure, height=390)
        style_dashboard_figure(level_figure, height=390)
        chart_config = {"displayModeBar": False, "displaylogo": False}

        render_anchor("section-distribution")
        with st.container(border=True):
            render_section_header("成绩分布与等级占比", "分", "展示当前分析列的分数区间和等级结构。")
            distribution_column, level_column = st.columns(2)
            with distribution_column:
                st.plotly_chart(
                    distribution_figure,
                    width="stretch",
                    config=chart_config,
                )
            with level_column:
                render_anchor("section-level-structure")
                st.plotly_chart(
                    level_figure,
                    width="stretch",
                    config=chart_config,
                )

        render_anchor("section-subjects")
        subject_average_figure = None
        with st.container(border=True):
            render_section_header(
                "各科平均分",
                "科",
                "按原始平均分展示；不同满分科目暂不适合直接比较得分高低。",
            )
            if subject_averages.empty:
                st.info("当前未识别到两个及以上有效科目。")
            else:
                subject_average_figure = build_subject_average_figure(subject_averages)
                style_dashboard_figure(subject_average_figure, height=400)
                st.plotly_chart(
                    subject_average_figure,
                    width="stretch",
                    config=chart_config,
                )

        detail_df = pd.DataFrame(display_score_details)
        if class_col is None:
            detail_df = detail_df.drop(columns=["班级"])
        if student_id_col is None:
            detail_df = detail_df.drop(columns=["学号"])
        detail_df.insert(0, "名次", range(1, len(detail_df) + 1))

        excellent_df = pd.DataFrame(
            build_display_student_list(
                identity_analysis_result,
                identity_records,
                result_key="excellent_students",
            )
        )
        fail_df = pd.DataFrame(
            build_display_student_list(
                identity_analysis_result,
                identity_records,
                result_key="fail_students",
            )
        )
        for students_df in (excellent_df, fail_df):
            if class_col is None and "班级" in students_df:
                students_df.drop(columns=["班级"], inplace=True)
            if student_id_col is None and "学号" in students_df:
                students_df.drop(columns=["学号"], inplace=True)

        report_excellent_df = pd.DataFrame(
            build_display_student_list(
                identity_analysis_result,
                identity_records,
                result_key="excellent_students",
                contextualize_duplicate_names=True,
            )
        )
        report_fail_df = pd.DataFrame(
            build_display_student_list(
                identity_analysis_result,
                identity_records,
                result_key="fail_students",
                contextualize_duplicate_names=True,
            )
        )

        if analysis_mode == "analysis_center":
            current_report_name = st.session_state.get("word_report_exam_name") or Path(
                st.session_state.get("current_exam_file_name", "本次考试")
            ).stem
            if grade_overview_context is not None:
                identity_records_by_index = deepcopy(
                    grade_overview_context.identity_records_by_index
                )
                subject_scores_by_index = deepcopy(
                    grade_overview_context.subject_scores_by_index
                )
            else:
                try:
                    (
                        identity_records_by_index,
                        subject_scores_by_index,
                    ) = build_exam_identity_snapshot(
                        df,
                        name_col=name_col,
                        class_col=class_col,
                        student_id_col=student_id_col,
                        score_options=score_options,
                    )
                except ValueError as exc:
                    st.error(f"保存当前考试学生身份映射失败：{exc}")
                    st.stop()
            snapshot_full_score_by_column = dict(
                full_score_settings.get(score_context_key, {})
            )
            snapshot_full_score_by_column[
                clean_column_name(score_col)
            ] = float(full_score)
            cache_current_exam_snapshot(
                st.session_state,
                {
                    "analysis_result": analysis_result,
                    "excellent_df": report_excellent_df,
                    "fail_df": report_fail_df,
                    "distribution": distribution,
                    "distribution_figure": distribution_figure,
                    "level_figure": level_figure,
                    "subject_average_figure": subject_average_figure,
                    "selected_class": selected_class,
                    "score_col": score_col,
                    "full_score": float(full_score),
                    "excellent_percent": float(effective_excellent_percent),
                    "report_name": current_report_name,
                    "score_context_key": score_context_key,
                    "name_col": name_col,
                    "class_col": class_col,
                    "student_id_col": student_id_col,
                    "score_options": list(score_options),
                    "identity_records_by_index": identity_records_by_index,
                    "subject_scores_by_index": subject_scores_by_index,
                    "full_score_by_column": snapshot_full_score_by_column,
                },
            )
            if current_exam_context is None:
                current_exam_context = build_exam_context(
                    file_content=uploaded_file.getvalue(),
                    file_name=st.session_state.get(
                        "current_exam_file_name",
                        getattr(uploaded_file, "name", "当前考试.xlsx"),
                    ),
                    sheet_name=selected_sheet,
                    exam_name=current_report_name,
                    name_column=name_col,
                    class_column=class_col,
                    student_id_column=student_id_col,
                    score_columns=score_options,
                    identity_records_by_index=identity_records_by_index,
                    subject_scores_by_index=subject_scores_by_index,
                )
            st.session_state["current_exam_context"] = current_exam_context
            snapshot_for_config = st.session_state["current_exam_snapshot"]
            subject_excellent_settings = st.session_state.get(
                "subject_analysis_excellent_percent_by_context",
                {},
            )
            existing_exam_config = st.session_state.get("current_exam_config")
            if (
                grade_overview_page_state is not None
                and existing_exam_config is not None
                and getattr(existing_exam_config, "exam_id", None)
                == current_exam_context.exam_id
            ):
                candidate_exam_config = existing_exam_config
            else:
                try:
                    candidate_exam_config = build_exam_config(
                        exam_context=current_exam_context,
                        snapshot=snapshot_for_config,
                        full_score_by_subject=full_score_settings.get(
                            score_context_key,
                            {},
                        ),
                        excellent_percent_by_subject=subject_excellent_settings.get(
                            score_context_key,
                            {},
                        ),
                    )
                except (TypeError, ValueError):
                    candidate_exam_config = existing_exam_config
                if candidate_exam_config is not None:
                    st.session_state["current_exam_config"] = candidate_exam_config
            current_page_state = grade_overview_page_state
            if current_page_state is None:
                current_page_state = PageState(
                    exam_id=current_exam_context.exam_id,
                    page_name="grade_overview",
                    selected_subject=score_col,
                    selected_classes=(
                        ()
                        if selected_class == "全部学生"
                        else (str(selected_class),)
                    ),
                    config_overrides={},
                )
            st.session_state["current_page_state"] = current_page_state

        render_anchor("section-details")
        with st.container(border=True):
            render_section_header("完整成绩明细", "明", "当前筛选条件下的有效成绩与等级。")
            st.dataframe(detail_df, width="stretch")

        render_anchor("section-excellent")
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_section_header("优秀名单", "优")
                if excellent_df.empty:
                    st.info("本次没有优秀学生。")
                else:
                    st.dataframe(excellent_df, width="stretch")

        with right:
            render_anchor("section-improvement")
            with st.container(border=True):
                render_section_header("待提升名单", "升")
                if fail_df.empty:
                    st.info("本次暂无待提升学生。")
                else:
                    st.dataframe(fail_df, width="stretch")

        excel_file = export_score_result_to_bytes(export_analysis_result)
        render_anchor("section-export")
        with st.container(border=True):
            render_section_header("导出中心", "出", "下载 Excel 数据结果，或生成包含当前图表的 Word 分析报告。")
            st.markdown(
                '<div class="export-subsection"><h3 class="export-subtitle">Excel 数据结果</h3>'
                '<p class="export-description">保留现有成绩分析导出格式。</p></div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "下载完整成绩分析 Excel",
                data=excel_file,
                file_name="学生成绩统计结果.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
            )

            st.markdown(
                '<div class="export-subsection"><h3 class="export-subtitle">Word 成绩分析报告</h3>'
                '<p class="export-description">填写报告信息后，使用当前统计、名单和图表生成报告。</p></div>',
                unsafe_allow_html=True,
            )
            school_name = st.text_input("学校名称", key="word_report_school_name")
            exam_name = st.text_input("考试名称", key="word_report_exam_name")
            st.text_input(
                "分析范围" if selected_class == "全部学生" else "当前班级",
                value=selected_class,
                disabled=True,
            )
            st.text_input("当前分析科目", value=score_col, disabled=True)

            report_signature = (
                score_context_key,
                int(header_row_number),
                name_col,
                class_col,
                selected_class,
                score_col,
                float(full_score),
                float(effective_excellent_percent),
                school_name,
                exam_name,
            )
            if st.session_state.get("word_report_signature") != report_signature:
                st.session_state.pop("word_report_bytes", None)
                st.session_state.pop("word_report_filename", None)
                st.session_state.pop("word_report_signature", None)

            if st.button("生成 Word 报告", type="primary", width="stretch"):
                try:
                    report_bytes = build_score_report_bytes(
                        analysis_result=analysis_result,
                        excellent_df=report_excellent_df,
                        fail_df=report_fail_df,
                        distribution=distribution,
                        distribution_figure=distribution_figure,
                        level_figure=level_figure,
                        subject_average_figure=subject_average_figure,
                        selected_class=selected_class,
                        score_col=score_col,
                        full_score=full_score,
                        school_name=school_name,
                        exam_name=exam_name,
                    )
                    st.session_state["word_report_bytes"] = report_bytes
                    st.session_state["word_report_filename"] = safe_report_filename(
                        school_name=school_name,
                        class_name=selected_class,
                        subject_name=score_col,
                        exam_name=exam_name,
                    )
                    st.session_state["word_report_signature"] = report_signature
                except ReportGenerationError as exc:
                    st.error(str(exc))

            if st.session_state.get("word_report_signature") == report_signature:
                report_bytes = st.session_state.get("word_report_bytes")
                if report_bytes:
                    st.success("Word 报告生成成功，可点击下方按钮下载。")
                    st.download_button(
                        "下载 Word 成绩分析报告",
                        data=report_bytes,
                        file_name=st.session_state["word_report_filename"],
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    width="stretch",
                    )

    except Exception as e:
        st.error(f"读取 Excel 失败：{e}")

else:
    with sidebar_context:
        render_current_context("等待上传成绩表")
    if workflow_mode == "class_comparison":
        st.info("请先上传包含多个班级的成绩表，系统将生成班级对比结果。")
    elif analysis_mode == "report_center":
        st.info("请先上传成绩表，完成成绩分析后即可生成 Word 教学报告。")
    else:
        st.info("请先上传成绩表，系统将为你生成班级成绩概览。")
