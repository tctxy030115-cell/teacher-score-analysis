"""成绩分析助手应用服务。"""

from .class_analysis_service import get_or_build_class_result
from .config_resolver import effective_config
from .exam_config_builder import build_exam_config
from .exam_context_builder import build_exam_context
from .exam_import_service import (
    ColumnMappingError,
    EmptyExamFileError,
    EmptySheetError,
    ExamColumnMapping,
    ExamImportDraft,
    ExamImportError,
    ExamImportService,
    HeaderRowError,
    IdentityBuildError,
    SheetNotFoundError,
    WorkbookInspection,
    WorkbookReadError,
)
from .grade_overview_context_adapter import (
    GradeOverviewContextError,
    build_grade_overview_dataframe,
    build_grade_overview_identity_records,
)
from .request_builder import build_analysis_request
from .report_result_service import (
    analysis_result_to_legacy_dict,
    get_or_build_report_result,
)
from .result_adapter import adapt_analysis_result
from .result_key_builder import build_result_key
from .result_store import ResultStore
from .subject_analysis_service import get_or_build_subject_result

__all__ = (
    "ResultStore",
    "ColumnMappingError",
    "EmptyExamFileError",
    "EmptySheetError",
    "ExamColumnMapping",
    "ExamImportDraft",
    "ExamImportError",
    "ExamImportService",
    "HeaderRowError",
    "IdentityBuildError",
    "SheetNotFoundError",
    "WorkbookInspection",
    "WorkbookReadError",
    "GradeOverviewContextError",
    "adapt_analysis_result",
    "analysis_result_to_legacy_dict",
    "build_analysis_request",
    "build_exam_config",
    "build_exam_context",
    "build_grade_overview_dataframe",
    "build_grade_overview_identity_records",
    "build_result_key",
    "effective_config",
    "get_or_build_report_result",
    "get_or_build_class_result",
    "get_or_build_subject_result",
)
