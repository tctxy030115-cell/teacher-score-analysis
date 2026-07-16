from dataclasses import dataclass
import math
import re

import pandas as pd
import plotly.graph_objects as go

from chart_logic import (
    LEVEL_NAMES,
    apply_plotly_font_family,
    calculate_score_distribution,
    classify_score_rows,
)
from grade_logic import format_class_value, normalize_excellent_percent


SUMMARY_COLUMNS = [
    "班级",
    "原始记录数",
    "有效人数",
    "跳过人数",
    "平均分",
    "平均得分率",
    "最高分",
    "最低分",
    "及格人数",
    "及格率",
    "优秀人数",
    "优秀率",
    "待提升人数",
    "待提升率",
]
LEVEL_COLUMNS = ["班级", "等级", "人数", "占比"]
EXCLUDED_COLUMNS = ["班级", "原始记录数", "跳过人数", "排除原因"]
FAIRNESS_NOTICE = (
    "班级人数、学生基础和缺考情况可能不同，本模块用于观察本次考试的成绩结构，"
    "不直接作为教学质量评价依据。"
)


@dataclass
class ClassComparisonResult:
    summary: pd.DataFrame
    levels: pd.DataFrame
    excluded: pd.DataFrame

    @property
    def is_comparable(self):
        return len(self.summary) >= 2


def _empty_result():
    return ClassComparisonResult(
        summary=pd.DataFrame(columns=SUMMARY_COLUMNS),
        levels=pd.DataFrame(columns=LEVEL_COLUMNS),
        excluded=pd.DataFrame(columns=EXCLUDED_COLUMNS),
    )


def _natural_sort_key(value):
    parts = re.split(r"(\d+)", value.casefold())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part)


def natural_sort_class_names(values):
    class_names = {
        formatted
        for value in values
        if (formatted := format_class_value(value))
    }
    return sorted(class_names, key=_natural_sort_key)


def _invalid_class_reason(classified_rows):
    reasons = set(classified_rows["无效原因"].dropna())
    if reasons == {"分数为空或非数字"}:
        return "无有效成绩：当前成绩列全部为空或非数字"
    return "无有效成绩：全部记录均不符合有效成绩规则"


def build_class_comparison(
    dataframe,
    *,
    class_column,
    name_column,
    score_column,
    selected_classes,
    full_score,
    excellent_percent=90,
):
    selected = natural_sort_class_names(selected_classes)
    if len(selected) < 2:
        return _empty_result()

    working = pd.DataFrame(
        {
            "_班级": dataframe[class_column].copy(),
            "_姓名": dataframe[name_column].copy(),
            "_成绩": dataframe[score_column].copy(),
        },
        index=dataframe.index,
    )
    working["_班级"] = working["_班级"].apply(format_class_value)
    working = working[working["_班级"].isin(selected)].copy()

    summary_rows = []
    level_rows = []
    excluded_rows = []
    effective_excellent_percent = normalize_excellent_percent(excellent_percent)

    for class_name in selected:
        class_rows = working[working["_班级"] == class_name]
        raw_count = len(class_rows)
        if raw_count == 0:
            excluded_rows.append(
                {
                    "班级": class_name,
                    "原始记录数": 0,
                    "跳过人数": 0,
                    "排除原因": "无有效成绩：未找到该班级记录",
                }
            )
            continue

        classified = classify_score_rows(
            class_rows["_姓名"],
            class_rows["_成绩"],
            full_score=full_score,
        )
        valid = classified[classified["无效原因"].isna()]
        valid_count = len(valid)
        skipped_count = raw_count - valid_count
        if valid_count == 0:
            excluded_rows.append(
                {
                    "班级": class_name,
                    "原始记录数": raw_count,
                    "跳过人数": skipped_count,
                    "排除原因": _invalid_class_reason(classified),
                }
            )
            continue

        scores = valid["分数"].astype(float)
        distribution = calculate_score_distribution(
            scores,
            full_score=full_score,
            excellent_percent=effective_excellent_percent,
        )
        level_counts = dict(zip(distribution["档位"], distribution["人数"]))
        level_percentages = dict(zip(distribution["档位"], distribution["占比"]))
        improve_count = int(level_counts["待提升"])
        excellent_count = int(level_counts["优秀"])
        pass_count = valid_count - improve_count
        average_score = float(scores.mean())

        summary_rows.append(
            {
                "班级": class_name,
                "原始记录数": raw_count,
                "有效人数": valid_count,
                "跳过人数": skipped_count,
                "平均分": average_score,
                "平均得分率": average_score / float(full_score) * 100,
                "最高分": float(scores.max()),
                "最低分": float(scores.min()),
                "及格人数": pass_count,
                "及格率": pass_count / valid_count * 100,
                "优秀人数": excellent_count,
                "优秀率": excellent_count / valid_count * 100,
                "待提升人数": improve_count,
                "待提升率": improve_count / valid_count * 100,
            }
        )
        for level_name in LEVEL_NAMES:
            level_rows.append(
                {
                    "班级": class_name,
                    "等级": level_name,
                    "人数": int(level_counts[level_name]),
                    "占比": float(level_percentages[level_name]),
                }
            )

    return ClassComparisonResult(
        summary=pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS),
        levels=pd.DataFrame(level_rows, columns=LEVEL_COLUMNS),
        excluded=pd.DataFrame(excluded_rows, columns=EXCLUDED_COLUMNS),
    )


def _extreme_class_names(summary, column, mode):
    target = summary[column].max() if mode == "max" else summary[column].min()
    names = [
        row["班级"]
        for _, row in summary.iterrows()
        if math.isclose(float(row[column]), float(target), rel_tol=1e-9, abs_tol=1e-9)
    ]
    return "、".join(names), float(target)


def build_comparison_conclusion(summary):
    if len(summary) < 2:
        return ""

    highest_names, highest_rate = _extreme_class_names(summary, "平均得分率", "max")
    lowest_names, lowest_rate = _extreme_class_names(summary, "平均得分率", "min")
    pass_names, _ = _extreme_class_names(summary, "及格率", "max")
    excellent_names, _ = _extreme_class_names(summary, "优秀率", "max")
    improve_names, _ = _extreme_class_names(summary, "待提升率", "max")
    gap = highest_rate - lowest_rate
    if gap < 3:
        difference_text = "各班整体水平较为接近"
    elif gap <= 8:
        difference_text = "各班之间存在一定差异"
    else:
        difference_text = "各班整体表现差异较为明显"

    return (
        f"本次考试共对比{len(summary)}个班级，总有效人数为{int(summary['有效人数'].sum())}人。"
        f"平均得分率最高的班级为{highest_names}（{highest_rate:.1f}%），"
        f"最低的班级为{lowest_names}（{lowest_rate:.1f}%），"
        f"最大差距为{gap:.1f}个百分点，{difference_text}。"
        f"及格率最高的班级为{pass_names}；优秀率最高的班级为{excellent_names}；"
        f"本次考试待提升率相对较高的班级为{improve_names}。"
    )


def _apply_comparison_layout(figure, title, class_names, yaxis_title):
    tick_angle = -35 if len(class_names) > 6 else 0
    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin={"l": 52, "r": 32, "t": 62, "b": 70 if tick_angle else 54},
        height=420,
        hoverlabel={"bgcolor": "#ffffff", "font_color": "#334155"},
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    figure.update_xaxes(
        title_text="班级",
        categoryorder="array",
        categoryarray=class_names,
        tickangle=tick_angle,
        automargin=True,
        showgrid=False,
    )
    figure.update_yaxes(
        title_text=yaxis_title,
        range=[0, 105],
        ticksuffix="%",
        gridcolor="#E8EEF6",
        rangemode="tozero",
    )
    return apply_plotly_font_family(figure)


def build_average_rate_figure(summary):
    class_names = summary["班级"].tolist()
    customdata = summary[["平均分", "有效人数"]].values.tolist()
    figure = go.Figure(
        go.Bar(
            x=class_names,
            y=summary["平均得分率"],
            customdata=customdata,
            marker={"color": "#4F8DE8", "line": {"color": "#2563EB", "width": 1}},
            text=[f"{value:.1f}%" for value in summary["平均得分率"]],
            texttemplate="%{text}",
            textposition="outside",
            hovertemplate=(
                "班级：%{x}<br>平均得分率：%{y:.1f}%"
                "<br>平均分：%{customdata[0]:.2f}<br>有效人数：%{customdata[1]}<extra></extra>"
            ),
        )
    )
    return _apply_comparison_layout(
        figure,
        "各班平均得分率对比",
        class_names,
        "平均得分率",
    )


def build_pass_excellent_figure(summary):
    class_names = summary["班级"].tolist()
    figure = go.Figure()
    for name, column, color in (
        ("及格率", "及格率", "#719FE1"),
        ("优秀率", "优秀率", "#2563EB"),
    ):
        figure.add_trace(
            go.Bar(
                name=name,
                x=class_names,
                y=summary[column],
                marker={"color": color},
                text=[f"{value:.1f}%" for value in summary[column]],
                texttemplate="%{text}",
                textposition="outside",
                hovertemplate=f"班级：%{{x}}<br>{name}：%{{y:.1f}}%<extra></extra>",
            )
        )
    figure.update_layout(barmode="group")
    return _apply_comparison_layout(
        figure,
        "各班及格率与优秀率对比",
        class_names,
        "比率",
    )


def build_level_structure_figure(levels):
    level_styles = (
        ("优秀", "#22C55E", "#0F172A"),
        ("良好", "#3B82F6", "#FFFFFF"),
        ("中等", "#EAB308", "#1F2937"),
        ("及格", "#A855F7", "#FFFFFF"),
        ("待提升", "#EF4444", "#FFFFFF"),
    )

    def format_inside_label(count, percentage):
        if percentage >= 8:
            return f"{int(count)}人<br>{percentage:.1f}%"
        if percentage >= 4:
            return f"{percentage:.1f}%"
        return ""

    class_names = levels["班级"].drop_duplicates().tolist()
    figure = go.Figure()
    for level_name, color, text_color in level_styles:
        level_data = (
            levels[levels["等级"] == level_name]
            .set_index("班级")
            .reindex(class_names)
        )
        inside_text = [
            format_inside_label(count, percentage)
            for count, percentage in zip(level_data["人数"], level_data["占比"])
        ]
        figure.add_trace(
            go.Bar(
                name=level_name,
                x=class_names,
                y=level_data["占比"],
                customdata=level_data[["人数"]].values.tolist(),
                marker={"color": color},
                width=0.62,
                text=inside_text,
                texttemplate="%{text}",
                textposition="inside",
                insidetextanchor="middle",
                constraintext="inside",
                textfont={"color": text_color, "size": 12},
                hovertemplate=(
                    f"班级：%{{x}}<br>等级：{level_name}"
                    "<br>人数：%{customdata[0]}"
                    "<br>占有效人数比例：%{y:.1f}%<extra></extra>"
                ),
            )
        )
    figure = _apply_comparison_layout(
        figure,
        "各班成绩等级结构",
        class_names,
        "等级占比",
    )
    figure.update_layout(
        barmode="stack",
        bargap=0.35,
        title={
            "y": 0.98,
            "yanchor": "top",
            "yref": "container",
            "automargin": True,
        },
        margin={"l": 52, "r": 32, "t": 128, "b": 70 if len(class_names) > 6 else 54},
        legend={
            "orientation": "h",
            "traceorder": "normal",
            "x": 0,
            "xanchor": "left",
            "y": 1.02,
            "yanchor": "bottom",
            "yref": "paper",
            "font": {"size": 13},
        },
    )
    figure.update_yaxes(
        range=[0, 100],
        gridcolor="#E5E7EB",
        gridwidth=1,
        zerolinecolor="#CBD5E1",
        zerolinewidth=1,
    )
    return apply_plotly_font_family(figure)
