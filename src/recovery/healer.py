from __future__ import annotations

from orchestrator.interfaces import Healer, OrchestrationContext
from orchestrator.result import ExecutionResult
from recovery.classifier import FailureClassifier, FailureType


class SelfHealer(Healer):
    def __init__(self, classifier: FailureClassifier, max_rounds: int = 2) -> None:
        self._classifier = classifier
        self._max_rounds = max(1, max_rounds)

    def heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        if attempt >= self._max_rounds:
            return ExecutionResult.failure(
                "Healing failed: exceeded max healing rounds.",
                {
                    "attempt": attempt,
                    "query": context.query,
                },
                next_action="abort",
            )

        failure_type = self._classifier.classify(failed_result)

        if failure_type in {FailureType.TIMEOUT, FailureType.TOOL_ERROR, FailureType.DEPENDENCY_FAILURE}:
            return ExecutionResult.success(
                {
                    "attempt": attempt,
                    "failure_type": failure_type.value,
                },
                next_action="retry_execute",
            )

        if failure_type is FailureType.PLANNING_FAILURE:
            return ExecutionResult.success(
                {
                    "attempt": attempt,
                    "failure_type": failure_type.value,
                },
                next_action="replan",
            )

        if failure_type is FailureType.EMPTY_RETRIEVAL:
            return ExecutionResult.success(
                {
                    "attempt": attempt,
                    "failure_type": failure_type.value,
                },
                next_action="replan",
            )

        return ExecutionResult.failure(
            f"Healing failed: no strategy for {failure_type.value}.",
            {
                "attempt": attempt,
                "failure_type": failure_type.value,
            },
            next_action="abort",
        )
