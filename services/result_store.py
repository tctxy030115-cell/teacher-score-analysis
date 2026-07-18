"""与页面和 session_state 无关的纯内存分析结果仓库。"""

from __future__ import annotations

from copy import deepcopy

from models import AnalysisResult, ResultKey


class ResultStore:
    """按 ResultKey 隔离保存 AnalysisResult，并保护内部对象引用。"""

    def __init__(self) -> None:
        self._results: dict[ResultKey, AnalysisResult] = {}

    def save(self, result_key: ResultKey, result: AnalysisResult) -> None:
        """深复制结果后保存；相同 key 覆盖原结果。"""

        self._results[result_key] = deepcopy(result)

    def get(self, result_key: ResultKey) -> AnalysisResult | None:
        """返回结果副本；不存在时返回 None。"""

        result = self._results.get(result_key)
        return deepcopy(result) if result is not None else None

    def exists(self, result_key: ResultKey) -> bool:
        """判断当前仓库是否包含指定 ResultKey。"""

        return result_key in self._results

    def clear(self) -> None:
        """清空当前 ResultStore 实例的全部结果。"""

        self._results.clear()
