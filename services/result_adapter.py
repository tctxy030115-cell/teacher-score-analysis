"""将旧字典分析结果转换为统一 AnalysisResult 契约。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping

from models import AnalysisResult, ResultKey, ResultMetadata, ResultPayload


_SUMMARY_FIELDS = {
    "current_class",
    "current_subject",
}

_METRIC_FIELDS = {
    "student_count",
    "average_score",
    "highest_score",
    "lowest_score",
    "excellent_count",
    "good_count",
    "pass_count",
    "fail_count",
    "excellent_rate",
    "good_rate",
    "pass_rate",
    "fail_rate",
    "full_score",
    "excellent_percent",
    "good_percent",
    "pass_percent",
}

_TABLE_FIELDS = {
    "score_details",
    "excellent_students",
    "fail_students",
}

_CONTAINER_FIELDS = (
    "summary",
    "metrics",
    "tables",
    "charts",
    "extra",
)


def _merge_explicit_container(
    destination: dict[str, Any],
    extra: dict[str, Any],
    field_name: str,
    value: Any,
) -> None:
    if isinstance(value, Mapping):
        destination.update(value)
    else:
        extra[field_name] = value


def adapt_analysis_result(
    result_key: ResultKey,
    legacy_result: Mapping[str, Any],
    *,
    subject: str | None = None,
    created_at: datetime | None = None,
) -> AnalysisResult:
    """深复制并分类旧结果，不修改输入或任何外部状态。"""

    copied_result = deepcopy(dict(legacy_result))
    summary: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    tables: dict[str, Any] = {}
    charts: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    destinations = {
        "summary": summary,
        "metrics": metrics,
        "tables": tables,
        "charts": charts,
        "extra": extra,
    }

    for field_name in _CONTAINER_FIELDS:
        if field_name in copied_result:
            _merge_explicit_container(
                destinations[field_name],
                extra,
                field_name,
                copied_result.pop(field_name),
            )

    for field_name, value in copied_result.items():
        if field_name in _SUMMARY_FIELDS:
            summary[field_name] = value
        elif field_name in _METRIC_FIELDS:
            metrics[field_name] = value
        elif field_name in _TABLE_FIELDS:
            tables[field_name] = value
        elif field_name.endswith(("_figure", "_chart")):
            charts[field_name] = value
        else:
            extra[field_name] = value

    resolved_subject = subject
    if resolved_subject is None:
        current_subject = summary.get("current_subject")
        resolved_subject = (
            str(current_subject) if current_subject not in (None, "") else None
        )
    metadata = ResultMetadata(
        exam_id=result_key.exam_id,
        analysis_type=result_key.analysis_type,
        subject=resolved_subject,
        created_at=created_at,
    )
    payload = ResultPayload(
        summary=summary,
        metrics=metrics,
        tables=tables,
        charts=charts,
        extra=extra,
    )
    return AnalysisResult(
        result_key=result_key,
        metadata=metadata,
        payload=payload,
    )
