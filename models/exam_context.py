"""一场考试的只读数据模型骨架。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Hashable, Mapping


@dataclass(frozen=True)
class ExamMetadata:
    """考试文件及展示元数据。"""

    file_name: str
    file_fingerprint: str
    sheet_name: str
    exam_name: str | None = None
    exam_time: str | None = None


@dataclass(frozen=True)
class ExamSchema:
    """完成字段确认后的考试字段映射。"""

    name_column: str
    score_columns: tuple[str, ...]
    class_column: str | None = None
    student_id_column: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_columns", tuple(self.score_columns))


@dataclass(frozen=True)
class ExamContext:
    """页面只读的一场考试数据，不包含当前页面选择或分析规则。"""

    exam_id: str
    metadata: ExamMetadata
    schema: ExamSchema
    identity_records_by_index: Mapping[Hashable, Mapping[str, Any]] = field(
        default_factory=dict
    )
    subject_scores_by_index: Mapping[Hashable, Mapping[str, Any]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not str(self.exam_id).strip():
            raise ValueError("exam_id 不能为空。")
