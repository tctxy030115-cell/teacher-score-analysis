"""考试分析规则的数据模型骨架。"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping


def _validate_percent(name: str, value: float) -> None:
    numeric_value = float(value)
    if not isfinite(numeric_value) or not 0 <= numeric_value <= 100:
        raise ValueError(f"{name} 必须是 0 到 100 之间的有限数值。")


@dataclass(frozen=True)
class SubjectConfig:
    """单个科目的满分及可选页面规则覆盖。"""

    full_score: float
    excellent_percent: float | None = None
    pass_percent: float = 60.0

    def __post_init__(self) -> None:
        numeric_full_score = float(self.full_score)
        if not isfinite(numeric_full_score) or numeric_full_score <= 0:
            raise ValueError("full_score 必须是大于 0 的有限数值。")
        if self.excellent_percent is not None:
            _validate_percent("excellent_percent", self.excellent_percent)
        _validate_percent("pass_percent", self.pass_percent)


@dataclass(frozen=True)
class AnalysisRules:
    """考试默认及格、优秀和等级规则。"""

    pass_percent: float = 60.0
    excellent_percent: float = 90.0
    levels: Mapping[str, float] = field(
        default_factory=lambda: {
            "excellent": 90.0,
            "good": 80.0,
            "pass": 60.0,
        }
    )

    def __post_init__(self) -> None:
        _validate_percent("pass_percent", self.pass_percent)
        _validate_percent("excellent_percent", self.excellent_percent)
        for level_name, percent in self.levels.items():
            _validate_percent(f"levels[{level_name!r}]", percent)


@dataclass(frozen=True)
class ExamConfig:
    """通过 exam_id 与 ExamContext 关联的可版本化分析配置。"""

    exam_id: str
    version: int = 1
    subjects: Mapping[str, SubjectConfig] = field(default_factory=dict)
    rules: AnalysisRules = field(default_factory=AnalysisRules)
    page_overrides: Mapping[str, Mapping[str, SubjectConfig]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not str(self.exam_id).strip():
            raise ValueError("exam_id 不能为空。")
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise ValueError("version 必须是正整数。")
        if self.version < 1:
            raise ValueError("version 必须是正整数。")
