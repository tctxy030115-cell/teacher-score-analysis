"""学科分析结构化结果的缓存编排服务。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from models import AnalysisResult, ExamConfig, ExamContext, PageState

from .request_builder import build_analysis_request
from .result_adapter import adapt_analysis_result
from .result_key_builder import build_result_key
from .result_store import ResultStore


SubjectCalculation = Callable[[], Mapping[str, Any]]


def get_or_build_subject_result(
    exam_context: ExamContext | None,
    exam_config: ExamConfig | None,
    page_state: PageState | None,
    result_store: ResultStore | None,
    calculate_callback: SubjectCalculation,
) -> AnalysisResult | None:
    """优先返回缓存，未命中时调用旧计算回调并保存结构化结果。

    缺少任一新架构对象时返回 ``None``，由页面执行完整旧流程。
    本函数不读取页面状态，也不修改任何输入对象。
    """

    if (
        exam_context is None
        or exam_config is None
        or page_state is None
        or result_store is None
    ):
        return None

    analysis_request = build_analysis_request(
        exam_context,
        exam_config,
        page_state,
        analysis_type="subject_analysis",
    )
    result_key = build_result_key(analysis_request)
    cached_result = result_store.get(result_key)
    if cached_result is not None:
        return cached_result

    legacy_result = calculate_callback()
    if not isinstance(legacy_result, Mapping):
        raise TypeError("学科分析计算回调必须返回 Mapping。")
    result = adapt_analysis_result(
        result_key,
        legacy_result,
        subject=analysis_request.subject,
    )
    result_store.save(result_key, result)
    return result
