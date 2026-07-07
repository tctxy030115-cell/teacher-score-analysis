import pandas as pd
import streamlit as st

from grade_logic import (
    CLASS_COLUMN_ALIASES,
    NAME_COLUMN_ALIASES,
    SCORE_COLUMN_ALIASES,
    analyze_scores,
    build_class_options,
    build_dataframe_from_header,
    create_single_score_template,
    detect_header_row,
    export_score_result_to_bytes,
    find_first_matching_column,
    format_class_value,
    normalize_excellent_percent,
)


st.set_page_config(
    page_title="成绩分析工具",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background: #f6f8fb;
    }

    .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 2.5rem;
    }

    .page-header {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 1rem;
    }

    .page-title {
        color: #1f2937;
        font-size: 2rem;
        font-weight: 700;
        line-height: 1.25;
        margin: 0 0 .35rem 0;
    }

    .page-caption {
        color: #64748b;
        font-size: 1rem;
        margin: 0;
    }

    .section-label {
        color: #1f2937;
        font-size: 1.1rem;
        font-weight: 700;
        margin: .2rem 0 .6rem 0;
    }

    .section-note {
        color: #64748b;
        font-size: .92rem;
        margin: -.2rem 0 .75rem 0;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
    }

    .stButton button,
    .stDownloadButton button {
        border-radius: 8px;
        border: 1px solid #cbd5e1;
        background: #ffffff;
        color: #1f2937;
        font-weight: 600;
    }

    .stButton button:hover,
    .stDownloadButton button:hover {
        border-color: #2563eb;
        color: #1d4ed8;
    }

    @media (max-width: 720px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }

        .page-title {
            font-size: 1.55rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="page-header">
        <div class="page-title">📊 成绩分析工具</div>
        <p class="page-caption">上传 Excel，自动生成基础成绩分析。</p>
    </div>
    """,
    unsafe_allow_html=True,
)


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


with st.container(border=True):
    st.markdown('<div class="section-label">📁 文件操作</div>', unsafe_allow_html=True)
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


if uploaded_file:
    try:
        raw_df = pd.read_excel(uploaded_file, header=None)

        if raw_df.empty:
            st.error("Excel 表格没有可分析的数据。")
            st.stop()

        detected_header_row = detect_header_row(raw_df)
        default_header_row = detected_header_row + 1 if detected_header_row is not None else 1

        with st.container(border=True):
            st.markdown('<div class="section-label">🧭 表头设置</div>', unsafe_allow_html=True)
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
            st.markdown('<div class="section-label">📋 原始成绩预览</div>', unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True)

        if df.empty:
            st.error("表头下方没有可分析的数据。")
            st.stop()
        if len(df.columns) < 2:
            st.error("Excel 至少需要两列数据，才能分别选择姓名列和成绩列。")
            st.stop()

        columns = df.columns.tolist()
        matched_name_col = find_first_matching_column(columns, NAME_COLUMN_ALIASES)
        matched_score_col = find_first_matching_column(columns, SCORE_COLUMN_ALIASES)
        matched_class_col = find_first_matching_column(columns, CLASS_COLUMN_ALIASES)

        name_default_index = pick_column_index(columns, matched_name_col, 0)
        score_default_index = pick_column_index(columns, matched_score_col, 1)
        class_default_index = pick_column_index(columns, matched_class_col, 0)

        with st.container(border=True):
            st.markdown('<div class="section-label">✅ 选择分析对象</div>', unsafe_allow_html=True)
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
            st.markdown('<div class="section-label">📐 评价标准</div>', unsafe_allow_html=True)
            st.markdown(
                '<p class="section-note">默认规则：优秀≥满分的90%，良好≥80%，及格≥60%。请确认当前科目满分。</p>',
                unsafe_allow_html=True,
            )
            col_full_score, col_excellent_percent = st.columns(2)
            full_score = col_full_score.number_input(
                "本次考试满分",
                min_value=1.0,
                value=100.0,
                step=1.0,
            )
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

        selected["姓名"] = selected[name_col].astype(str).str.replace("\u3000", "", regex=False).str.strip()
        selected["分数"] = pd.to_numeric(selected[score_col], errors="coerce")

        valid_scores = selected[
            (selected["姓名"] != "")
            & (selected["姓名"].str.lower() != "nan")
            & selected["分数"].notna()
            & (selected["分数"] >= 0)
        ].copy()

        skipped_count = len(selected) - len(valid_scores)
        if skipped_count > 0:
            st.warning(f"已跳过 {skipped_count} 行姓名为空、分数为空、分数不是数字或分数为负数的数据。")

        if valid_scores.empty:
            if class_col is not None and selected_class != "全部班级":
                st.error("当前班级没有可分析的有效成绩。")
            else:
                st.error("没有可分析的有效成绩，请检查姓名列和分析科目 / 成绩列。")
            st.stop()

        student_scores = dict(zip(valid_scores["姓名"], valid_scores["分数"]))
        analysis_result = analyze_scores(
            student_scores,
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
            current_class=selected_class,
            current_subject=score_col,
        )

        with st.container(border=True):
            st.markdown('<div class="section-label">📊 基础统计</div>', unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("参考人数", analysis_result["student_count"])
            c2.metric("平均分", f"{analysis_result['average_score']:.2f}")
            c3.metric("最高分", f"{analysis_result['highest_score']:.0f}")
            c4.metric("最低分", f"{analysis_result['lowest_score']:.0f}")
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("优秀学生", analysis_result["excellent_count"])
            c6.metric("不及格人数", analysis_result["fail_count"])
            c7.metric("及格率", f"{analysis_result['pass_rate']:.1f}%")
            c8.metric("优秀率", f"{analysis_result['excellent_rate']:.1f}%")

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
            st.markdown('<div class="section-label">📄 完整成绩明细</div>', unsafe_allow_html=True)
            st.dataframe(detail_df, use_container_width=True)

        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                st.markdown('<div class="section-label">🌟 优秀名单</div>', unsafe_allow_html=True)
                if excellent_df.empty:
                    st.info("本次没有优秀学生。")
                else:
                    st.dataframe(excellent_df, use_container_width=True)

        with right:
            with st.container(border=True):
                st.markdown('<div class="section-label">⚠️ 不及格名单</div>', unsafe_allow_html=True)
                if fail_df.empty:
                    st.info("本次没有不及格学生。")
                else:
                    st.dataframe(fail_df, use_container_width=True)

        excel_file = export_score_result_to_bytes(analysis_result)
        with st.container(border=True):
            st.markdown('<div class="section-label">📤 导出结果</div>', unsafe_allow_html=True)
            st.download_button(
                "下载完整成绩分析 Excel",
                data=excel_file,
                file_name="学生成绩统计结果.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    except Exception as e:
        st.error(f"读取 Excel 失败：{e}")

else:
    st.info("请先上传一份 Excel 成绩表。")
