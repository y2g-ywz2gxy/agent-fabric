from __future__ import annotations

from enum import Enum

from orchestrator.result import ExecutionResult


class FailureType(str, Enum):
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    DEPENDENCY_FAILURE = "dependency_failure"
    EMPTY_RETRIEVAL = "empty_retrieval"
    PLANNING_FAILURE = "planning_failure"
    UNKNOWN = "unknown"


class FailureClassifier:
    def classify(self, result: ExecutionResult) -> FailureType:
        error = (result.error or "").lower()

        if "timeout" in error or "超时" in error:
            return FailureType.TIMEOUT
        if "tool" in error or "工具" in error:
            return FailureType.TOOL_ERROR
        if "dependency" in error or "依赖" in error:
            return FailureType.DEPENDENCY_FAILURE
        if "empty retrieval" in error or "空检索" in error:
            return FailureType.EMPTY_RETRIEVAL
        if "planning" in error or "plan" in error or result.next_action == "replan":
            return FailureType.PLANNING_FAILURE

        return FailureType.UNKNOWN
