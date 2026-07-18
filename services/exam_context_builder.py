"""将现有上传分析数据转换为只读 ExamContext。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Hashable, Mapping, Sequence

from models import ExamContext, ExamMetadata, ExamSchema


def _normalize_schema_value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value).replace("\u3000", " ").strip()


def _build_exam_identity(
    *,
    file_fingerprint: str,
    sheet_name: str,
    name_column: str,
    class_column: str | None,
    student_id_column: str | None,
    score_columns: Sequence[str],
) -> str:
    schema_signature = json.dumps(
        {
            "sheet_name": _normalize_schema_value(sheet_name),
            "name_column": _normalize_schema_value(name_column),
            "class_column": _normalize_schema_value(class_column),
            "student_id_column": _normalize_schema_value(student_id_column),
            "score_columns": [
                _normalize_schema_value(column) for column in score_columns
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    identity_digest = hashlib.sha256(
        f"{file_fingerprint}\n{schema_signature}".encode("utf-8")
    ).hexdigest()
    return f"exam-{identity_digest[:24]}"


def build_exam_context(
    *,
    file_content: bytes,
    file_name: str,
    sheet_name: str,
    exam_name: str | None,
    name_column: str,
    class_column: str | None,
    student_id_column: str | None,
    score_columns: Sequence[str],
    identity_records_by_index: Mapping[Hashable, Mapping[str, Any]],
    subject_scores_by_index: Mapping[Hashable, Mapping[str, Any]],
) -> ExamContext:
    """使用现有稳定行索引数据创建 ExamContext，不修改输入映射。"""

    file_fingerprint = hashlib.sha256(file_content).hexdigest()
    normalized_score_columns = tuple(score_columns)
    exam_id = _build_exam_identity(
        file_fingerprint=file_fingerprint,
        sheet_name=sheet_name,
        name_column=name_column,
        class_column=class_column,
        student_id_column=student_id_column,
        score_columns=normalized_score_columns,
    )
    return ExamContext(
        exam_id=exam_id,
        metadata=ExamMetadata(
            file_name=str(file_name),
            file_fingerprint=file_fingerprint,
            sheet_name=str(sheet_name),
            exam_name=exam_name,
        ),
        schema=ExamSchema(
            name_column=str(name_column),
            class_column=None if class_column is None else str(class_column),
            student_id_column=(
                None if student_id_column is None else str(student_id_column)
            ),
            score_columns=normalized_score_columns,
        ),
        identity_records_by_index=deepcopy(identity_records_by_index),
        subject_scores_by_index=deepcopy(subject_scores_by_index),
    )
