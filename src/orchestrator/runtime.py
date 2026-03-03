from __future__ import annotations

from typing import Any, Mapping

from observability.metrics import MetricsCollector
from orchestrator.interfaces import Executor, Healer, OrchestrationContext, Planner, Router
from orchestrator.result import ExecutionResult
from orchestrator.state import RuntimeState, RuntimeStateMachine
from registry.schema import RegistrySnapshot


class RuleBasedExecutor:
    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        lowered = query.lower()
        if "timeout" in lowered or "超时" in lowered:
            return ExecutionResult.failure(
                "Execution failed: timeout while calling tool.",
                {"plan": plan_data},
            )
        if "dependency" in lowered or "依赖" in lowered:
            return ExecutionResult.failure(
                "Execution failed: dependency service unavailable.",
                {"plan": plan_data},
            )
        if "tool_error" in lowered or "工具异常" in lowered:
            return ExecutionResult.failure(
                "Execution failed: tool error.",
                {"plan": plan_data},
            )

        response = {
            "answer": "任务已通过自适应编排链路执行完成。",
            "plan_steps": len(plan_data.get("steps", [])),
            "plan": plan_data,
        }
        return ExecutionResult.success(response, next_action="completed")


class AdaptiveOrchestratorRuntime:
    def __init__(
        self,
        router: Router,
        planner: Planner,
        executor: Executor,
        healer: Healer,
        metrics: MetricsCollector | None = None,
        *,
        max_replans: int = 2,
    ) -> None:
        self.router = router
        self.planner = planner
        self.executor = executor
        self.healer = healer
        self.metrics = metrics or MetricsCollector()
        self.max_replans = max(0, max_replans)
        self.state_machine = RuntimeStateMachine()

    def run(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        context = OrchestrationContext(query=query, registry_snapshot=registry_snapshot)
        heal_attempt = 0
        planning_retry = 0

        self.state_machine.transition_to(RuntimeState.ROUTING)
        route_result = self.router.route(query, registry_snapshot)
        self.metrics.record("routing.completed", scene=route_result.data.get("scene", "unknown"))
        if not route_result.ok:
            return self._fail(route_result)
        context.route_data = route_result.data

        while planning_retry <= self.max_replans:
            self.state_machine.transition_to(RuntimeState.PLANNING)
            plan_result = self.planner.plan(query, context.route_data or {}, retry=planning_retry)
            self.metrics.record("planning.completed", retry=planning_retry)

            if not plan_result.ok:
                heal_result = self._heal(plan_result, context, attempt=heal_attempt)
                heal_attempt += 1
                if heal_result.ok and heal_result.next_action == "replan":
                    planning_retry += 1
                    continue
                return self._fail(heal_result)

            context.plan_data = plan_result.data
            replan_requested = False
            execute_retry = 0
            while True:
                self.state_machine.transition_to(RuntimeState.EXECUTING)
                execute_result = self.executor.execute(query, context.plan_data or {})
                self.metrics.record("execution.completed", success=execute_result.ok)

                if execute_result.ok:
                    self.state_machine.transition_to(RuntimeState.COMPLETED)
                    return execute_result

                heal_result = self._heal(execute_result, context, attempt=heal_attempt)
                heal_attempt += 1
                if heal_result.ok and heal_result.next_action == "retry_execute":
                    execute_retry += 1
                    if execute_retry > self.max_replans:
                        return self._fail(
                            ExecutionResult.failure(
                                "Execution failed: exceeded retry_execute limit."
                            )
                        )
                    continue

                if heal_result.ok and heal_result.next_action == "replan":
                    planning_retry += 1
                    replan_requested = True
                    break

                if heal_result.ok and heal_result.next_action == "completed":
                    self.state_machine.transition_to(RuntimeState.COMPLETED)
                    return heal_result

                return self._fail(heal_result)

            if replan_requested:
                continue

        return self._fail(ExecutionResult.failure("Execution failed: exceeded replan limit."))

    def _heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        self.state_machine.transition_to(RuntimeState.HEALING)
        self.metrics.record("healing.triggered", attempt=attempt)
        heal_result = self.healer.heal(failed_result, context, attempt=attempt)
        if heal_result.ok:
            self.metrics.record("healing.success", action=heal_result.next_action or "none")
        else:
            self.metrics.record("healing.failed", error=heal_result.error or "unknown")
        return heal_result

    def _fail(self, result: ExecutionResult) -> ExecutionResult:
        if self.state_machine.state is not RuntimeState.FAILED:
            self.state_machine.transition_to(RuntimeState.FAILED)
        return result
