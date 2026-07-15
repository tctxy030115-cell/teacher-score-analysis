import pandas as pd
import streamlit as st

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
    build_class_options,
    build_dataframe_from_header,
    create_single_score_template,
    detect_header_row,
    export_score_result_to_bytes,
    find_first_matching_column,
    find_first_matching_score_column,
    format_class_value,
    get_column_full_score,
    get_total_score_notice,
    has_analyzable_columns,
    normalize_excellent_percent,
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

inject_global_styles()
render_sidebar()
render_page_header()


def pick_column_index(columns, matched_column, fallback_index=0):
    if matched_column in columns:
        return columns.index(matched_column)
    return min(fallback_index, len(columns) - 1)


def pick_default_class_index(class_options):
    current_class = st.session_state.get("selected_class")
    if current_class in class_options:
        return class_options.index(current_class)
    if "2401" in class_options:
        st.session_state["selected_class"] = "2401"
        return class_options.index("2401")
    st.session_state["selected_class"] = "全部班级"
    return 0


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
            selected_sheet = st.selectbox(
                "选择要分析的工作表",
                sheet_names,
                index=0,
            )
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

        name_default_index = pick_column_index(columns, matched_name_col, 0)
        score_default_index = pick_column_index(columns, matched_score_col, 1)
        class_default_index = pick_column_index(columns, matched_class_col, 0)

        with st.container(border=True):
            render_section_header("选择分析对象", "选")
            st.markdown(
                '<p class="section-note">先确认姓名列和班级范围，再选择要分析的科目或成绩列。</p>',
                unsafe_allow_html=True,
            )

            col_name, col_subject = st.columns(2)
            name_col = col_name.selectbox(
                "姓名列",
                columns,
                index=name_default_index,
            )
            score_col = col_subject.selectbox(
                "分析科目 / 成绩列",
                columns,
                index=score_default_index,
            )

            class_col = None
            selected_class = "全部班级"
            if matched_class_col is not None:
                col_class, col_filter = st.columns(2)
                class_col = col_class.selectbox(
                    "班级列",
                    columns,
                    index=class_default_index,
                )
                class_options = build_class_options(df[class_col])
                selected_class = col_filter.selectbox(
                    "查看班级",
                    class_options,
                    index=pick_default_class_index(class_options),
                    key="selected_class",
                )

        with st.container(border=True):
            render_section_header("评价标准", "标")
            st.markdown(
                '<p class="section-note">默认规则：优秀≥满分的90%，良好≥80%，及格≥60%。请确认当前分析列满分。</p>',
                unsafe_allow_html=True,
            )
            score_context_key = build_full_score_context_key(uploaded_file.getvalue(), selected_sheet)
            full_score_settings = st.session_state.setdefault("full_score_by_context", {})
            suggested_full_score = get_column_full_score(
                full_score_settings,
                score_context_key,
                score_col,
            )
            col_full_score, col_excellent_percent = st.columns(2)
            full_score = col_full_score.number_input(
                "当前分析列满分",
                min_value=1.0,
                value=suggested_full_score,
                step=1.0,
                key=f"full_score::{score_context_key}::{score_col}",
            )
            set_column_full_score(full_score_settings, score_context_key, score_col, full_score)
            col_full_score.caption("请填写当前所选成绩列的满分，例如数学 120 分、总分 800 分。")
            excellent_percent = col_excellent_percent.number_input(
                "优秀线（%）",
                min_value=0.0,
                max_value=100.0,
                value=90.0,
                step=1.0,
            )
            effective_excellent_percent = normalize_excellent_percent(excellent_percent)
            if excellent_percent < 60:
                st.warning("优秀线不能低于及格线 60%，本次分析将按 60% 处理。")
            total_score_notice = get_total_score_notice(score_col)
            if total_score_notice:
                st.info(total_score_notice)

        if name_col == score_col:
            st.error("请选择不同的姓名列和分析科目 / 成绩列。")
            st.stop()

        analysis_df = df.copy()
        if class_col is not None and selected_class != "全部班级":
            class_values = analysis_df[class_col].apply(format_class_value)
            analysis_df = analysis_df[class_values == selected_class].copy()

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

        render_anchor("core-statistics")
        with st.container(border=True):
            render_section_header("核心统计", "统", "当前班级与分析科目的关键成绩指标。")
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

        render_anchor("score-distribution")
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

        render_anchor("subject-analysis")
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

        with st.container(border=True):
            render_section_header("完整成绩明细", "明", "当前筛选条件下的有效成绩与等级。")
            st.dataframe(detail_df, width="stretch")

        render_anchor("excellent-list")
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_section_header("优秀名单", "优")
                if excellent_df.empty:
                    st.info("本次没有优秀学生。")
                else:
                    st.dataframe(excellent_df, width="stretch")

        with right:
            render_anchor("improve-list")
            with st.container(border=True):
                render_section_header("待提升名单", "升")
                if fail_df.empty:
                    st.info("本次暂无待提升学生。")
                else:
                    st.dataframe(fail_df, width="stretch")

        excel_file = export_score_result_to_bytes(analysis_result)
        render_anchor("export-center")
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
            st.text_input("当前班级", value=selected_class, disabled=True)
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
    st.info("请先上传一份 Excel 成绩表。")
