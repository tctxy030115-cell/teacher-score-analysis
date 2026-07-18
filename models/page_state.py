"""按考试和页面隔离的用户交互状态骨架。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import MutableMapping


@dataclass
class GradeOverviewState:
    selected_subject: str | None = None
    selected_class: str | None = None


@dataclass
class SubjectAnalysisState:
    selected_subject: str | None = None


@dataclass
class ClassAnalysisState:
    selected_subject: str | None = None
    selected_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.selected_classes = tuple(self.selected_classes)


@dataclass
class ReportCenterState:
    school_name: str = ""
    report_title: str = ""


@dataclass
class ExamPageState:
    grade_overview: GradeOverviewState = field(default_factory=GradeOverviewState)
    subject_analysis: SubjectAnalysisState = field(
        default_factory=SubjectAnalysisState
    )
    class_analysis: ClassAnalysisState = field(default_factory=ClassAnalysisState)
    report_center: ReportCenterState = field(default_factory=ReportCenterState)


@dataclass
class PageState:
    """兼容全局路由，并保存单个考试页面的并行状态档案。"""

    route: str = "home"
    by_exam: MutableMapping[str, ExamPageState] = field(default_factory=dict)
    exam_id: str | None = None
    page_name: str | None = None
    selected_subject: str | None = None
    selected_classes: tuple[str, ...] = ()
    config_overrides: MutableMapping[
        str,
        MutableMapping[str, float],
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.selected_classes = tuple(self.selected_classes)
