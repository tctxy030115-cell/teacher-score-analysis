"""成绩分析助手未来架构的数据模型公共接口。"""

from .analysis_request import AnalysisRequest
from .exam_config import AnalysisRules, ExamConfig, SubjectConfig
from .exam_context import ExamContext, ExamMetadata, ExamSchema
from .page_state import (
    ClassAnalysisState,
    ExamPageState,
    GradeOverviewState,
    PageState,
    ReportCenterState,
    SubjectAnalysisState,
)
from .result import AnalysisResult, ResultKey
from .result_payload import ResultMetadata, ResultPayload

__all__ = (
    "AnalysisRequest",
    "AnalysisResult",
    "AnalysisRules",
    "ClassAnalysisState",
    "ExamConfig",
    "ExamContext",
    "ExamMetadata",
    "ExamPageState",
    "ExamSchema",
    "GradeOverviewState",
    "PageState",
    "ReportCenterState",
    "ResultMetadata",
    "ResultPayload",
    "ResultKey",
    "SubjectAnalysisState",
    "SubjectConfig",
)
