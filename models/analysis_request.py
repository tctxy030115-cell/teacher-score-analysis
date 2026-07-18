"""一次分析请求的不可变描述。"""

from __future__ import annotations

from dataclasses import dataclass
import re


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class AnalysisRequest:
    """描述用户针对一场考试发起的分析，不包含考试数据或结果。"""

    exam_id: str
    page_name: str
    analysis_type: str
    subject: str | None
    selected_classes: tuple[str, ...]
    config_version: int
    config_signature: str
    state_signature: str

    def __post_init__(self) -> None:
        if not str(self.exam_id).strip():
            raise ValueError("exam_id 不能为空。")
        if not str(self.page_name).strip():
            raise ValueError("page_name 不能为空。")
        if not str(self.analysis_type).strip():
            raise ValueError("analysis_type 不能为空。")
        if isinstance(self.config_version, bool) or not isinstance(
            self.config_version,
            int,
        ):
            raise ValueError("config_version 必须是正整数。")
        if self.config_version < 1:
            raise ValueError("config_version 必须是正整数。")
        for name, signature in (
            ("config_signature", self.config_signature),
            ("state_signature", self.state_signature),
        ):
            if not _SHA256_PATTERN.fullmatch(str(signature)):
                raise ValueError(f"{name} 必须是 SHA-256 十六进制字符串。")
        normalized_subject = (
            str(self.subject).strip() if self.subject is not None else None
        )
        object.__setattr__(self, "subject", normalized_subject or None)
        object.__setattr__(
            self,
            "selected_classes",
            tuple(sorted(str(value) for value in self.selected_classes)),
        )
