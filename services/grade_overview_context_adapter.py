"""将 ExamContext 适配为旧年级总览计算所需的临时数据。"""

from __future__ import annotations

from copy import deepcopy
from typing import Hashable, Iterable

import pandas as pd

from models import ExamContext


class GradeOverviewContextError(ValueError):
    """ExamContext 无法完整提供年级总览事实数据。"""


def _require_subject(exam_context: ExamContext, subject: str) -> None:
    if subject not in exam_context.schema.score_columns:
        raise GradeOverviewContextError(f"ExamContext 不包含成绩列：{subject}。")


def build_grade_overview_dataframe(exam_context: ExamContext) -> pd.DataFrame:
    """按原始行 index 构造旧年级分析可读取的临时 DataFrame。"""

    if not isinstance(exam_context, ExamContext):
        raise TypeError("exam_context 必须是 ExamContext。")

    schema = exam_context.schema
    rows: list[dict[str, object]] = []
    row_indices: list[Hashable] = []
    for row_index, identity_record in exam_context.identity_records_by_index.items():
        row_scores = exam_context.subject_scores_by_index.get(row_index)
        if row_scores is None:
            raise GradeOverviewContextError(
                f"ExamContext 第 {row_index!r} 行缺少科目成绩映射。"
            )

        row: dict[str, object] = {}
        if schema.student_id_column is not None:
            row[schema.student_id_column] = deepcopy(identity_record.get("学号", ""))
        if schema.class_column is not None:
            row[schema.class_column] = deepcopy(identity_record.get("班级", ""))
        row[schema.name_column] = deepcopy(identity_record.get("姓名", ""))
        for subject in schema.score_columns:
            if subject not in row_scores:
                raise GradeOverviewContextError(
                    f"ExamContext 第 {row_index!r} 行缺少成绩列：{subject}。"
                )
            row[subject] = deepcopy(row_scores[subject])
        row_indices.append(row_index)
        rows.append(row)

    return pd.DataFrame(rows, index=pd.Index(row_indices))


def build_grade_overview_identity_records(
    exam_context: ExamContext,
    subject: str,
    valid_row_indices: Iterable[Hashable],
) -> list[dict[str, object]]:
    """按有效行 index 复制已有身份，并绑定 Context 中的当前科目成绩。"""

    if not isinstance(exam_context, ExamContext):
        raise TypeError("exam_context 必须是 ExamContext。")
    _require_subject(exam_context, subject)

    records: list[dict[str, object]] = []
    for row_index in valid_row_indices:
        identity_record = exam_context.identity_records_by_index.get(row_index)
        row_scores = exam_context.subject_scores_by_index.get(row_index)
        if identity_record is None or row_scores is None:
            raise GradeOverviewContextError(
                f"ExamContext 无法按原始 index 关联第 {row_index!r} 行。"
            )
        if subject not in row_scores:
            raise GradeOverviewContextError(
                f"ExamContext 第 {row_index!r} 行缺少成绩列：{subject}。"
            )

        numeric_score = pd.to_numeric(
            pd.Series([row_scores[subject]]),
            errors="coerce",
        ).iloc[0]
        if pd.isna(numeric_score):
            raise GradeOverviewContextError(
                f"第 {row_index!r} 行不是当前分析的有效成绩。"
            )

        record = deepcopy(identity_record)
        record["分数"] = float(numeric_score)
        records.append(record)
    return records
