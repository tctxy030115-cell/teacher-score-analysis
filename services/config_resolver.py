"""解析页面临时配置、考试配置和系统默认配置的最终有效值。"""

from __future__ import annotations

from typing import Mapping

from grade_logic import clean_column_name
from models import ExamConfig, PageState, SubjectConfig


def _subject_value(
    values: Mapping[str, object],
    subject: str,
) -> object | None:
    if subject in values:
        return values[subject]
    for configured_subject, value in values.items():
        if clean_column_name(configured_subject) == subject:
            return value
    return None


def _override_value(
    overrides: Mapping[str, object],
    field_name: str,
    fallback: float,
) -> float:
    value = overrides.get(field_name)
    if value is None:
        return float(fallback)
    return float(value)


def effective_config(
    exam_config: ExamConfig | None,
    page_state: PageState | None,
    subject: str,
    system_default: SubjectConfig,
) -> SubjectConfig:
    """返回新的科目配置，按页面、考试、系统默认逐字段回退。"""

    cleaned_subject = clean_column_name(subject)
    exam_subject = None
    if exam_config is not None:
        exam_subject = _subject_value(exam_config.subjects, cleaned_subject)

    full_score = (
        exam_subject.full_score
        if isinstance(exam_subject, SubjectConfig)
        else system_default.full_score
    )
    pass_percent = (
        exam_subject.pass_percent
        if isinstance(exam_subject, SubjectConfig)
        else (
            exam_config.rules.pass_percent
            if exam_config is not None
            else system_default.pass_percent
        )
    )
    if isinstance(exam_subject, SubjectConfig):
        excellent_percent = exam_subject.excellent_percent
    else:
        excellent_percent = None
    if excellent_percent is None:
        excellent_percent = (
            exam_config.rules.excellent_percent
            if exam_config is not None
            else system_default.excellent_percent
        )
    if excellent_percent is None:
        excellent_percent = system_default.excellent_percent

    overrides: Mapping[str, object] = {}
    page_matches_exam = (
        page_state is not None
        and (
            exam_config is None
            or not page_state.exam_id
            or page_state.exam_id == exam_config.exam_id
        )
    )
    if page_matches_exam and page_state is not None:
        subject_overrides = _subject_value(
            page_state.config_overrides,
            cleaned_subject,
        )
        if isinstance(subject_overrides, Mapping):
            overrides = subject_overrides

    return SubjectConfig(
        full_score=_override_value(overrides, "full_score", full_score),
        excellent_percent=_override_value(
            overrides,
            "excellent_percent",
            excellent_percent,
        ),
        pass_percent=_override_value(
            overrides,
            "pass_percent",
            pass_percent,
        ),
    )
