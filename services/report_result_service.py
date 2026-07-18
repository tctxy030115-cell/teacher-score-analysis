"""报告中心获取结构化结果及兼容旧报告字典的业务服务。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from models import AnalysisRequest, AnalysisResult, ResultPayload

from .result_adapter import adapt_analysis_result
from .result_key_builder import build_result_key
from .result_store import ResultStore


def get_or_build_report_result(
    analysis_request: AnalysisRequest | None,
    result_store: ResultStore | None,
    legacy_analysis_result: Mapping[str, Any],
) -> AnalysisResult | None:
    """优先读取缓存，未命中时适配旧结果；缺少新对象时返回 None。"""

    if analysis_request is None or result_store is None:
        return None
    result_key = build_result_key(analysis_request)
    cached_result = result_store.get(result_key)
    if cached_result is not None:
        return cached_result
    result = adapt_analysis_result(
        result_key,
        legacy_analysis_result,
        subject=analysis_request.subject,
    )
    result_store.save(result_key, result)
    return result


def analysis_result_to_legacy_dict(
    result: AnalysisResult | None,
    *,
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    """将统一结果还原为 Word 接口使用的旧字典，或返回 fallback 副本。"""

    if result is None:
        return deepcopy(dict(fallback))
    if isinstance(result.payload, Mapping):
        return deepcopy(dict(result.payload))
    if not isinstance(result.payload, ResultPayload):
        raise TypeError("AnalysisResult.payload 必须是 ResultPayload 或 Mapping。")
    legacy_result: dict[str, Any] = {}
    for container in (
        result.payload.summary,
        result.payload.metrics,
        result.payload.tables,
        result.payload.charts,
        result.payload.extra,
    ):
        legacy_result.update(deepcopy(dict(container)))
    return legacy_result
