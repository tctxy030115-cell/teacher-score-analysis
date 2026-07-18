"""根据考试、规则和页面状态构造稳定的分析请求。"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from grade_logic import clean_column_name
from models import AnalysisRequest, ExamConfig, ExamContext, PageState, SubjectConfig


def _stable_sha256(payload: Mapping[str, Any]) -> str:
    normalized_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(normalized_json.encode("utf-8")).hexdigest()


def _subject_value(values: Mapping[str, Any], subject: str | None) -> Any:
    if subject is None:
        return None
    if subject in values:
        return values[subject]
    for configured_subject, value in values.items():
        if clean_column_name(configured_subject) == subject:
            return value
    return None


def _subject_config_payload(subject_config: Any) -> Mapping[str, float] | None:
    if not isinstance(subject_config, SubjectConfig):
        return None
    return {
        "full_score": float(subject_config.full_score),
        "pass_percent": float(subject_config.pass_percent),
        "excellent_percent": (
            float(subject_config.excellent_percent)
            if subject_config.excellent_percent is not None
            else None
        ),
    }


def _relevant_override_payload(
    page_state: PageState,
    subject: str | None,
) -> Mapping[str, float]:
    override = _subject_value(page_state.config_overrides, subject)
    if not isinstance(override, Mapping):
        return {}
    return {
        str(name): float(value)
        for name, value in override.items()
    }


def build_analysis_request(
    exam_context: ExamContext,
    exam_config: ExamConfig,
    page_state: PageState,
    *,
    analysis_type: str | None = None,
) -> AnalysisRequest:
    """纯函数构造 AnalysisRequest，并拒绝跨考试输入。"""

    exam_ids = (
        exam_context.exam_id,
        exam_config.exam_id,
        page_state.exam_id,
    )
    if any(not exam_id for exam_id in exam_ids) or len(set(exam_ids)) != 1:
        raise ValueError(
            "ExamContext、ExamConfig 与 PageState 的 exam_id 必须一致。"
        )
    page_name = str(page_state.page_name or "").strip()
    if not page_name:
        raise ValueError("PageState.page_name 不能为空。")
    resolved_analysis_type = str(analysis_type or page_name).strip()
    if not resolved_analysis_type:
        raise ValueError("analysis_type 不能为空。")

    subject = (
        clean_column_name(page_state.selected_subject)
        if page_state.selected_subject is not None
        else None
    )
    selected_classes = tuple(
        sorted(str(value) for value in page_state.selected_classes)
    )
    subject_config = _subject_value(exam_config.subjects, subject)
    config_signature = _stable_sha256(
        {
            "config_version": exam_config.version,
            "subject": subject,
            "subject_config": _subject_config_payload(subject_config),
            "global_rules": {
                "pass_percent": float(exam_config.rules.pass_percent),
                "excellent_percent": float(
                    exam_config.rules.excellent_percent
                ),
                "levels": {
                    str(name): float(value)
                    for name, value in exam_config.rules.levels.items()
                },
            },
        }
    )
    state_signature = _stable_sha256(
        {
            "page_name": page_name,
            "subject": subject,
            "selected_classes": selected_classes,
            "config_override": _relevant_override_payload(
                page_state,
                subject,
            ),
        }
    )

    return AnalysisRequest(
        exam_id=exam_context.exam_id,
        page_name=page_name,
        analysis_type=resolved_analysis_type,
        subject=subject,
        selected_classes=selected_classes,
        config_version=exam_config.version,
        config_signature=config_signature,
        state_signature=state_signature,
    )
