"""根据既有考试档案和业务配置构造 ExamConfig。"""

from __future__ import annotations

from typing import Any, Mapping

from grade_logic import clean_column_name, get_full_score_suggestion
from models import AnalysisRules, ExamConfig, ExamContext, SubjectConfig


def _normalize_config_mapping(values: Mapping[object, Any] | None) -> dict[str, Any]:
    return {
        clean_column_name(column): value
        for column, value in (values or {}).items()
    }


def build_exam_config(
    *,
    exam_context: ExamContext,
    snapshot: Mapping[str, Any],
    full_score_by_subject: Mapping[object, Any] | None = None,
    excellent_percent_by_subject: Mapping[object, Any] | None = None,
    config_version: int = 1,
) -> ExamConfig:
    """创建只包含评价规则的配置，不修改输入对象。"""

    configured_full_scores = _normalize_config_mapping(
        snapshot.get("full_score_by_column") or {}
    )
    configured_full_scores.update(
        _normalize_config_mapping(full_score_by_subject)
    )
    configured_excellent_percents = _normalize_config_mapping(
        excellent_percent_by_subject
    )

    current_subject = clean_column_name(snapshot.get("score_col"))
    if current_subject and current_subject not in configured_full_scores:
        current_full_score = snapshot.get("full_score")
        if current_full_score is not None:
            configured_full_scores[current_subject] = current_full_score

    default_excellent_percent = float(snapshot.get("excellent_percent", 90.0))
    subjects: dict[str, SubjectConfig] = {}
    for subject in exam_context.schema.score_columns:
        cleaned_subject = clean_column_name(subject)
        full_score = configured_full_scores.get(cleaned_subject)
        if full_score is None:
            full_score = get_full_score_suggestion(subject).value
        excellent_percent = configured_excellent_percents.get(
            cleaned_subject,
            default_excellent_percent,
        )
        subjects[cleaned_subject] = SubjectConfig(
            full_score=float(full_score),
            excellent_percent=float(excellent_percent),
            pass_percent=60.0,
        )

    return ExamConfig(
        exam_id=exam_context.exam_id,
        version=config_version,
        subjects=subjects,
        rules=AnalysisRules(
            pass_percent=60.0,
            excellent_percent=default_excellent_percent,
        ),
    )
