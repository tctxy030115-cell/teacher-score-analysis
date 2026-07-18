"""分析结果身份与通用结果容器骨架。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Hashable


RequestSignature = str | tuple[tuple[str, Hashable], ...]


@dataclass(frozen=True)
class ResultKey:
    """唯一标识一份考试分析结果及其配置版本。"""

    exam_id: str
    config_version: int
    analysis_type: str
    request_signature: RequestSignature = ()

    def __post_init__(self) -> None:
        if not str(self.exam_id).strip():
            raise ValueError("exam_id 不能为空。")
        if isinstance(self.config_version, bool) or not isinstance(
            self.config_version, int
        ):
            raise ValueError("config_version 必须是正整数。")
        if self.config_version < 1:
            raise ValueError("config_version 必须是正整数。")
        if not str(self.analysis_type).strip():
            raise ValueError("analysis_type 不能为空。")
        if isinstance(self.request_signature, str):
            if not re.fullmatch(r"[0-9a-f]{64}", self.request_signature):
                raise ValueError(
                    "字符串 request_signature 必须是 SHA-256 十六进制字符串。"
                )
        else:
            object.__setattr__(
                self,
                "request_signature",
                tuple(self.request_signature),
            )
from .result_payload import AnalysisResult
