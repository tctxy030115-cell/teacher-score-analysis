"""结构化分析结果契约及旧 AnalysisResult 构造兼容层。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from .result import ResultKey


@dataclass(frozen=True)
class ResultMetadata:
    """标识一份分析结果所属的考试、类型和科目。"""

    exam_id: str
    analysis_type: str
    subject: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not str(self.exam_id).strip():
            raise ValueError("exam_id 不能为空。")
        if not str(self.analysis_type).strip():
            raise ValueError("analysis_type 不能为空。")
        normalized_subject = (
            str(self.subject).strip() if self.subject is not None else None
        )
        object.__setattr__(self, "subject", normalized_subject or None)


@dataclass(frozen=True)
class ResultPayload:
    """按摘要、指标、表格、图表和扩展字段组织的结果载荷。"""

    summary: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    tables: Mapping[str, Any] = field(default_factory=dict)
    charts: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, init=False)
class AnalysisResult:
    """统一结果契约，同时兼容旧的 key + dict payload 构造方式。"""

    result_key: ResultKey
    metadata: ResultMetadata
    payload: ResultPayload | Mapping[str, Any]

    def __init__(
        self,
        result_key: ResultKey | None = None,
        metadata: ResultMetadata | None = None,
        payload: ResultPayload | Mapping[str, Any] | None = None,
        *,
        key: ResultKey | None = None,
    ) -> None:
        if result_key is not None and key is not None and result_key != key:
            raise ValueError("result_key 与兼容参数 key 必须一致。")
        resolved_key = result_key if result_key is not None else key
        if resolved_key is None:
            raise ValueError("result_key 不能为空。")
        resolved_metadata = metadata or ResultMetadata(
            exam_id=resolved_key.exam_id,
            analysis_type=resolved_key.analysis_type,
        )
        if resolved_metadata.exam_id != resolved_key.exam_id:
            raise ValueError("metadata.exam_id 必须与 result_key.exam_id 一致。")
        if resolved_metadata.analysis_type != resolved_key.analysis_type:
            raise ValueError(
                "metadata.analysis_type 必须与 result_key.analysis_type 一致。"
            )
        resolved_payload = payload if payload is not None else ResultPayload()
        object.__setattr__(self, "result_key", resolved_key)
        object.__setattr__(self, "metadata", resolved_metadata)
        object.__setattr__(self, "payload", resolved_payload)

    @property
    def key(self) -> ResultKey:
        """兼容旧代码读取 result.key。"""

        return self.result_key
