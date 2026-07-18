"""学生身份键与展示数据适配，不包含成绩计算公式。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Hashable, Iterable

import pandas as pd

from grade_logic import (
    STUDENT_ID_COLUMN_ALIASES,
    clean_column_name,
    format_class_value,
)


def find_student_id_column(columns: Iterable[object]) -> str | None:
    """识别长期学生身份字段，不使用考号或准考证号。"""
    for alias in STUDENT_ID_COLUMN_ALIASES:
        for column in columns:
            if clean_column_name(column) == alias:
                return str(column)
    return None


def _normalize_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).replace("\u3000", "").strip()


def _build_identity_key(*, student_id: str, class_name: str, name: str) -> tuple[str, ...]:
    if student_id:
        return ("student_id", student_id)
    if class_name:
        return ("class_name", class_name, name)
    return ("name", name)


def build_student_identity_records(
    valid_scores: pd.DataFrame,
    *,
    class_column: str | None = None,
    student_id_column: str | None = None,
) -> list[dict[str, Any]]:
    """为有效成绩行生成身份键，并保留姓名、班级和学号展示字段。"""
    records: list[dict[str, Any]] = []
    for _, row in valid_scores.iterrows():
        name = _normalize_name(row["姓名"])
        if not name or name.lower() == "nan":
            raise ValueError("姓名为空，无法生成学生身份。")
        class_name = format_class_value(row[class_column]) if class_column else ""
        student_id = format_class_value(row[student_id_column]) if student_id_column else ""
        records.append(
            {
                "identity_key": _build_identity_key(
                    student_id=student_id,
                    class_name=class_name,
                    name=name,
                ),
                "姓名": name,
                "班级": class_name,
                "学号": student_id,
                "分数": float(row["分数"]),
            }
        )
    return records


def build_student_score_mapping(
    records: Iterable[dict[str, Any]],
) -> dict[Hashable, float]:
    """构造 analyze_scores 所需字典，重复身份明确报错而不静默覆盖。"""
    student_scores: dict[Hashable, float] = {}
    for record in records:
        identity_key = record["identity_key"]
        if identity_key in student_scores:
            raise ValueError(f"学生身份重复：{record['姓名']}。请检查学号、班级和姓名。")
        student_scores[identity_key] = float(record["分数"])
    return student_scores


def _identity_lookup(
    records: Iterable[dict[str, Any]],
) -> dict[Hashable, dict[str, Any]]:
    return {record["identity_key"]: record for record in records}


def _display_name(
    record: dict[str, Any],
    name_counts: dict[str, int],
    *,
    contextualize_duplicate_names: bool,
) -> str:
    name = record["姓名"]
    if not contextualize_duplicate_names or name_counts.get(name, 0) < 2:
        return name
    context = record["学号"] or record["班级"]
    return f"{name}（{context}）" if context else name


def build_display_score_details(
    analysis_result: dict[str, Any],
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """生成页面成绩明细，内部身份键不会进入展示字段。"""
    lookup = _identity_lookup(records)
    rows = []
    for identity_key, score, level in analysis_result["score_details"]:
        student = lookup[identity_key]
        rows.append(
            {
                "姓名": student["姓名"],
                "班级": student["班级"],
                "学号": student["学号"],
                "分数": score,
                "等级": level,
            }
        )
    return rows


def build_display_student_list(
    analysis_result: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    result_key: str,
    contextualize_duplicate_names: bool = False,
) -> list[dict[str, Any]]:
    """生成优秀或待提升展示名单，并保留班级和学号字段。"""
    record_list = list(records)
    lookup = _identity_lookup(record_list)
    name_counts = pd.Series([record["姓名"] for record in record_list]).value_counts().to_dict()
    rows = []
    for identity_key, score in analysis_result[result_key]:
        student = lookup[identity_key]
        rows.append(
            {
                "姓名": _display_name(
                    student,
                    name_counts,
                    contextualize_duplicate_names=contextualize_duplicate_names,
                ),
                "班级": student["班级"],
                "学号": student["学号"],
                "分数": score,
            }
        )
    return rows


def restore_analysis_result_display_names(
    analysis_result: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    contextualize_duplicate_names: bool = False,
) -> dict[str, Any]:
    """将分析结果中的内部身份键转换为仅供展示和导出的姓名。"""
    record_list = list(records)
    lookup = _identity_lookup(record_list)
    name_counts = pd.Series([record["姓名"] for record in record_list]).value_counts().to_dict()
    display_result = deepcopy(analysis_result)
    for result_key in ("score_details", "excellent_students", "fail_students"):
        for row in display_result[result_key]:
            student = lookup[row[0]]
            row[0] = _display_name(
                student,
                name_counts,
                contextualize_duplicate_names=contextualize_duplicate_names,
            )
    return display_result
