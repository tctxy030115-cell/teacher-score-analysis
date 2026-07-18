"""根据不可变分析请求生成稳定结果标识。"""

from __future__ import annotations

from hashlib import sha256
import json

from models import AnalysisRequest, ResultKey


def build_result_key(request: AnalysisRequest) -> ResultKey:
    """返回包含跨进程稳定 SHA-256 请求签名的 ResultKey。"""

    normalized_json = json.dumps(
        {
            "exam_id": request.exam_id,
            "page_name": request.page_name,
            "analysis_type": request.analysis_type,
            "subject": request.subject,
            "selected_classes": request.selected_classes,
            "config_version": request.config_version,
            "config_signature": request.config_signature,
            "state_signature": request.state_signature,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    request_signature = sha256(
        normalized_json.encode("utf-8")
    ).hexdigest()
    return ResultKey(
        exam_id=request.exam_id,
        config_version=request.config_version,
        analysis_type=request.analysis_type,
        request_signature=request_signature,
    )
