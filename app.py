from functools import partial

import pandas as pd
import streamlit as st

from class_comparison_logic import (
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
    build_full_score_context_key,
    build_dataframe_from_header,
    build_single_class_options,
    create_single_score_template,
    detect_header_row,
    export_score_result_to_bytes,
    filter_dataframe_by_class,
    find_first_matching_column,
    find_first_matching_score_column,
    format_class_value,
    get_column_full_score,
    get_total_score_notice,
    has_analyzable_columns,
    normalize_excellent_percent,
    resolve_column_selection,
    resolve_single_class_selection,
    set_column_full_score,
)
from report_logic import (
    ReportGenerationError,
    build_score_report_bytes,
    safe_report_filename,
)
from ui_components import (
    inject_global_styles,
    render_anchor,
    render_current_context,
    render_metric_grid,
    render_page_header,
    render_section_header,
    render_sidebar,
    style_dashboard_figure,
)


st.set_page_config(
    page_title="成绩分析工具",
    page_icon="📊",
    layout="wide",
)

st.session_state.setdefault("analysis_mode", "single_class")
analysis_mode = st.session_state["analysis_mode"]

inject_global_styles()
sidebar_context = render_sidebar(
    analysis_mode=analysis_mode,
    on_mode_change=partial(st.session_state.__setitem__, "analysis_mode"),
)
render_page_header()


def render_class_comparison_section(
    *,
    dataframe,
    class_col,
    name_col,
    score_col,
    full_score,
    excellent_percent,
    score_context_key,
):
    render_anchor("section-class-comparison")
    with st.container(border=True):
        render_section_header(
            "班级横向对比",
            "比",
            "选择两个或多个班级，对比同一成绩列下的平均得分率、及格率、优秀率和等级结构。",
        )
        if class_col is None:
            st.info("当前数据未识别到班级列，暂无法进行班级对比。")
            return
        if class_col in {name_col, score_col}:
            st.info("班级列需与姓名列和分析科目 / 成绩列不同，暂无法进行班级对比。")
            return

        class_options = natural_sort_class_names(dataframe[class_col])
        if len(class_options) < 2:
            st.info("当前数据只识别到一个班级，暂无法进行班级对比。")
            return

        selected_classes = st.multiselect(
            "选择对比班级",
            class_options,
            default=class_options[:6],
            key=f"class_comparison_classes::{score_context_key}::{class_col}",
        )
        st.caption(
            f"数据口径：当前工作表 · {score_col} · 满分 {float(full_score):g} 分 · "
            f"及格线 60% · 优秀线 {float(excellent_percent):g}%"
        )
        if len(selected_classes) > 10:
            st.warning("当前选择的班级较多，图表标签可能较密集；可减少班级数量以便阅读。")
        if len(selected_classes) < 2:
            st.info("请至少选择两个班级后生成对比。")
            return

        result = build_class_comparison(
            dataframe,
            class_column=class_col,
            name_column=name_col,
            score_column=score_col,
            selected_classes=selected_classes,
            full_score=full_score,
            excellent_percent=excellent_percent,
        )
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
    selected_sheet = None
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

        score_options = [
            column for column in columns if column not in {name_col, class_col}
        ]
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

        class_options = build_single_class_options(df[class_col]) if class_col is not None else []
        selected_class = resolve_single_class_selection(
            class_options,
            st.session_state.get("selected_class"),
        )

        with st.container(border=True):
            render_section_header("分析设置", "设", "选择当前分析范围与评价标准。")
            top_columns = st.columns(
                3 if analysis_mode == "single_class" and class_col is not None else 2
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

            if analysis_mode == "single_class" and class_col is not None and class_options:
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
            full_score_key = f"full_score::{score_context_key}::{score_col}"
            if full_score_key not in st.session_state:
                st.session_state[full_score_key] = get_column_full_score(
                    full_score_settings,
                    score_context_key,
                    score_col,
                )
            standard_columns = st.columns(3)
            full_score = standard_columns[0].number_input(
                "当前成绩列满分",
                min_value=1.0,
                step=1.0,
                key=full_score_key,
            )
            set_column_full_score(full_score_settings, score_context_key, score_col, full_score)

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

        effective_excellent_percent = normalize_excellent_percent(excellent_percent)
        if excellent_percent < 60:
            st.warning("优秀线不能低于及格线 60%，本次分析将按 60% 处理。")
        total_score_notice = get_total_score_notice(score_col)
        if total_score_notice:
            st.info(total_score_notice)

        if analysis_mode == "class_comparison":
            comparison_options = (
                natural_sort_class_names(df[class_col]) if class_col is not None else []
            )
            comparison_key = f"class_comparison_classes::{score_context_key}::{class_col}"
            comparison_selection = st.session_state.get(
                comparison_key,
                comparison_options[:6],
            )
            comparison_count = len(
                [value for value in comparison_selection if value in comparison_options]
            )
            summary_class = f"{comparison_count} 个班级"
        else:
            summary_class = selected_class if class_options or class_col is None else "未识别有效班级"

        with sidebar_context:
            render_current_context(f"{summary_class} · {score_col}")

        if analysis_mode == "single_class" and class_col is not None and not class_options:
            st.info("当前班级列没有识别到有效班级，暂无法进行单班成绩分析。")
            st.stop()

        if name_col == score_col:
            st.error("请选择不同的姓名列和分析科目 / 成绩列。")
            st.stop()

        if analysis_mode == "class_comparison":
            render_class_comparison_section(
                dataframe=df,
                class_col=class_col,
                name_col=name_col,
                score_col=score_col,
                full_score=full_score,
                excellent_percent=effective_excellent_percent,
                score_context_key=score_context_key,
            )
            st.stop()

        analysis_df = filter_dataframe_by_class(df, class_col, selected_class)

        selected_columns = [name_col, score_col]
        if class_col is not None and class_col not in selected_columns:
            selected_columns.insert(0, class_col)

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

        student_scores = dict(zip(valid_scores["姓名"], valid_scores["分数"]))
        analysis_result = analyze_scores(
            student_scores,
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
            current_class=selected_class,
            current_subject=score_col,
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
                st.plotly_chart(
                    level_figure,
                    width="stretch",
                    config=chart_config,
                )

        render_anchor("section-subjects")
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

        detail_df = pd.DataFrame(
            analysis_result["score_details"],
            columns=["姓名", "分数", "等级"],
        )
        detail_df.insert(0, "名次", range(1, len(detail_df) + 1))
        if class_col is not None:
            class_lookup = valid_scores.set_index("姓名")[class_col].to_dict()
            detail_df.insert(1, "班级", detail_df["姓名"].map(class_lookup))

        excellent_df = pd.DataFrame(
            analysis_result["excellent_students"],
            columns=["姓名", "分数"],
        )
        fail_df = pd.DataFrame(
            analysis_result["fail_students"],
            columns=["姓名", "分数"],
        )

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

        excel_file = export_score_result_to_bytes(analysis_result)
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
                        excellent_df=excellent_df,
                        fail_df=fail_df,
                        distribution=distribution,
                        distribution_figure=distribution_figure,
                        level_figure=level_figure,
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
    if analysis_mode == "class_comparison":
        st.info("请先上传包含多个班级的成绩表，系统将生成班级对比结果。")
    else:
        st.info("请先上传成绩表，系统将为你生成班级成绩概览。")
