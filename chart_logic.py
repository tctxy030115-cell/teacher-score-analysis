import pandas as pd
import plotly.graph_objects as go

from grade_logic import (
    SUBJECT_COLUMN_ALIASES,
    clean_column_name,
    normalize_excellent_percent,
    normalize_score_column_name,
)


LEVEL_NAMES = ["待提升", "及格", "中等", "良好", "优秀"]
LEVEL_COLORS = ["#94a3b8", "#7c8da6", "#6f8fa8", "#5f8299", "#4f7288"]
INVALID_REASON_ORDER = (
    "姓名为空",
    "分数为空或非数字",
    "分数小于 0",
    "分数高于当前满分",
)


def clean_score_series(values, full_score=100):
    scores = pd.to_numeric(pd.Series(values).copy(), errors="coerce")
    maximum = float(full_score)
    return scores[scores.notna() & (scores >= 0) & (scores <= maximum)].astype(float)


def classify_score_rows(name_values, score_values, full_score=100):
    names = pd.Series(name_values).copy().fillna("").astype(str)
    names = names.str.replace("\u3000", "", regex=False).str.strip()
    numeric_scores = pd.to_numeric(pd.Series(score_values).copy(), errors="coerce")
    reasons = pd.Series(None, index=names.index, dtype=object)

    name_empty = (names == "") | (names.str.lower() == "nan")
    reasons.loc[name_empty] = "姓名为空"
    reasons.loc[reasons.isna() & numeric_scores.isna()] = "分数为空或非数字"
    reasons.loc[reasons.isna() & (numeric_scores < 0)] = "分数小于 0"
    reasons.loc[reasons.isna() & (numeric_scores > float(full_score))] = "分数高于当前满分"

    return pd.DataFrame(
        {
            "姓名": names,
            "分数": numeric_scores.astype(float),
            "无效原因": reasons,
        },
        index=names.index,
    )


def count_invalid_reasons(classified_rows):
    reason_counts = classified_rows["无效原因"].value_counts()
    return {
        reason: int(reason_counts[reason])
        for reason in INVALID_REASON_ORDER
        if int(reason_counts.get(reason, 0)) > 0
    }


def build_invalid_data_warning(reason_counts, full_score):
    total = sum(reason_counts.values())
    if total == 0:
        return None

    lines = [
        f"已跳过 {total} 行无效数据（仅在本次分析中跳过，原始 Excel 未被修改）："
    ]
    for reason in INVALID_REASON_ORDER:
        count = int(reason_counts.get(reason, 0))
        if count == 0:
            continue
        if reason == "分数高于当前满分":
            label = f"分数高于当前满分 {_format_number(full_score)} 分"
        else:
            label = reason
        lines.append(f"- {label}：{count} 行")

    above_count = int(reason_counts.get("分数高于当前满分", 0))
    if above_count > 0 and above_count == max(reason_counts.values()):
        lines.append("\n高于当前满分是主要原因，请检查“当前分析列满分”设置。")
    return "\n".join(lines)


def _format_number(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _format_interval(lower_rate, upper_rate, full_score, include_upper=False):
    if upper_rate <= lower_rate:
        return "无区间"

    lower = lower_rate * full_score
    upper = upper_rate * full_score
    if float(full_score) == 100 and lower.is_integer() and upper.is_integer():
        lower_label = _format_number(lower)
        upper_label = _format_number(upper if include_upper else upper - 1)
        return f"{lower_label}–{upper_label}"

    closing = "]" if include_upper else ")"
    return f"[{_format_number(lower)}, {_format_number(upper)}{closing}"


def calculate_score_distribution(values, full_score=100, excellent_percent=90):
    maximum = float(full_score)
    excellent_rate = min(normalize_excellent_percent(excellent_percent), 100) / 100
    scores = clean_score_series(values, maximum)
    score_rates = scores / maximum if maximum > 0 else pd.Series(dtype=float)

    excellent_mask = score_rates >= excellent_rate
    good_mask = ~excellent_mask & (score_rates >= 0.8)
    middle_mask = ~excellent_mask & (score_rates >= 0.7) & (score_rates < 0.8)
    pass_mask = ~excellent_mask & (score_rates >= 0.6) & (score_rates < 0.7)
    improve_mask = ~(excellent_mask | good_mask | middle_mask | pass_mask)

    counts = [
        int(improve_mask.sum()),
        int(pass_mask.sum()),
        int(middle_mask.sum()),
        int(good_mask.sum()),
        int(excellent_mask.sum()),
    ]
    interval_rates = [
        (0, 0.6, False),
        (0.6, min(0.7, excellent_rate), False),
        (0.7, min(0.8, excellent_rate), False),
        (0.8, excellent_rate, False),
        (excellent_rate, 1, True),
    ]
    intervals = [
        _format_interval(lower, upper, maximum, include_upper)
        for lower, upper, include_upper in interval_rates
    ]

    total = len(scores)
    percentages = [count / total * 100 if total else 0.0 for count in counts]
    result = pd.DataFrame(
        {
            "档位": LEVEL_NAMES,
            "区间": intervals,
            "人数": counts,
            "占比": percentages,
        }
    )
    result.attrs["有效人数"] = total
    result.attrs["平均分"] = float(scores.mean()) if total else None
    return result


def calculate_subject_averages(dataframe, full_score=100):
    rows = []
    recognized_subjects = set(SUBJECT_COLUMN_ALIASES)
    for column in dataframe.columns:
        original_subject = clean_column_name(column)
        normalized_subject = normalize_score_column_name(column)
        if normalized_subject not in recognized_subjects:
            continue
        # 多科图比较原始平均分，只排除空值、非数字和负数；当前分析列满分不适用于其他科目。
        scores = pd.to_numeric(dataframe[column], errors="coerce")
        scores = scores[scores.notna() & (scores >= 0)].astype(float)
        if scores.empty:
            continue
        rows.append(
            {
                "科目": original_subject,
                "平均分": round(float(scores.mean()), 1),
                "有效人数": len(scores),
            }
        )

    result = pd.DataFrame(rows, columns=["科目", "平均分", "有效人数"])
    if len(result) < 2:
        return pd.DataFrame(columns=["科目", "平均分", "有效人数"])
    return result


def _apply_common_layout(figure, title, height=360):
    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#334155", "family": "Arial, sans-serif"},
        margin={"l": 42, "r": 24, "t": 58, "b": 42},
        height=height,
        hoverlabel={"bgcolor": "#ffffff", "font_color": "#334155"},
    )
    return figure


def build_distribution_figure(distribution):
    figure = go.Figure(
        go.Bar(
            x=distribution["区间"],
            y=distribution["人数"],
            customdata=distribution["占比"],
            marker={"color": "#64839a", "line": {"color": "#526f83", "width": 1}},
            text=distribution["人数"],
            texttemplate="%{y}",
            textposition="outside",
            hovertemplate="分数区间：%{x}<br>人数：%{y}<br>占比：%{customdata:.1f}%<extra></extra>",
        )
    )
    _apply_common_layout(figure, "成绩分布")
    figure.update_xaxes(title_text="分数区间", showgrid=False)
    figure.update_yaxes(title_text="学生人数", rangemode="tozero", gridcolor="#e2e8f0")

    average = distribution.attrs.get("平均分")
    if average is not None:
        figure.add_annotation(
            x=1,
            y=1.08,
            xref="paper",
            yref="paper",
            xanchor="right",
            showarrow=False,
            text=f"平均分：{average:.1f}",
            font={"color": "#64748b", "size": 13},
        )
    return figure


def build_level_donut_figure(distribution):
    total = int(distribution.attrs.get("有效人数", distribution["人数"].sum()))
    figure = go.Figure(
        go.Pie(
            labels=distribution["档位"],
            values=distribution["人数"],
            hole=0.58,
            sort=False,
            marker={"colors": LEVEL_COLORS, "line": {"color": "#ffffff", "width": 2}},
            textinfo="label+percent",
            hovertemplate="等级：%{label}<br>人数：%{value}<br>占比：%{percent}<extra></extra>",
        )
    )
    _apply_common_layout(figure, "成绩等级占比")
    figure.update_layout(
        showlegend=False,
        annotations=[
            {
                "text": f"{total}<br><span style='font-size:12px'>有效学生</span>",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 22, "color": "#334155"},
            }
        ],
    )
    return figure


def build_subject_average_figure(subject_averages):
    figure = go.Figure(
        go.Bar(
            x=subject_averages["科目"],
            y=subject_averages["平均分"],
            customdata=subject_averages["有效人数"],
            marker={"color": "#718da3", "line": {"color": "#5d788e", "width": 1}},
            text=subject_averages["平均分"],
            texttemplate="%{y:.1f}",
            textposition="outside",
            hovertemplate="科目：%{x}<br>平均分：%{y:.1f}<br>有效人数：%{customdata}<extra></extra>",
        )
    )
    _apply_common_layout(figure, "各科平均分对比", height=380)
    figure.update_xaxes(title_text="科目", showgrid=False)
    figure.update_yaxes(title_text="平均分", rangemode="tozero", gridcolor="#e2e8f0")
    return figure
