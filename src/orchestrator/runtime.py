# -*- coding: utf-8 -*-
"""
自适应编排运行时模块。

基于 AgentScope pipeline 串联 route -> plan -> execute，
并在失败后通过 healer 进行 LLM 自愈决策。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from agentscope.agent import AgentBase
from agentscope.message import Msg
from agentscope.pipeline import SequentialPipeline

from observability.metrics import MetricsCollector
from orchestrator.agentscope_runtime import run_async
from orchestrator.interfaces import Executor, Healer, OrchestrationContext, Planner, Router
from orchestrator.result import ExecutionResult
from orchestrator.state import RuntimeState, RuntimeStateMachine
from registry.schema import RegistrySnapshot


class _StageAgent(AgentBase):
    """将任意异步处理函数适配成 AgentScope Agent。"""

    def __init__(self, name: str, handler: Callable[[Msg | list[Msg] | None], Awaitable[Msg]]) -> None:
        super().__init__()
        self.name = name
        self._handler = handler
        self.register_state("name")

    async def observe(self, msg: Msg | list[Msg] | None) -> None:
        _ = msg

    async def reply(self, msg: Msg | list[Msg] | None = None) -> Msg:
        return await self._handler(msg)


class AdaptiveOrchestratorRuntime:
    """自适应编排运行时。"""

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
        self.last_context: OrchestrationContext | None = None

    def run(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        """执行一轮编排。"""
        self.state_machine = RuntimeStateMachine()
        context = OrchestrationContext(query=query, registry_snapshot=registry_snapshot)
        self.last_context = context

        heal_attempt = 0
        planning_retry = 0
        execute_retry = 0

        while planning_retry <= self.max_replans:
            route_result, plan_result, execute_result = self._run_pipeline_once(
                query=query,
                registry_snapshot=registry_snapshot,
                planning_retry=planning_retry,
                context=context,
            )

            if route_result.ok:
                context.route_data = route_result.data
            if plan_result.ok:
                context.plan_data = plan_result.data

            if execute_result.ok:
                self.state_machine.transition_to(RuntimeState.COMPLETED)
                return execute_result

            failed_result = self._pick_failed_result(route_result, plan_result, execute_result)
            heal_result = self._heal(failed_result, context, attempt=heal_attempt)
            heal_attempt += 1

            if heal_result.ok and heal_result.next_action == "retry_execute":
                execute_retry += 1
                if execute_retry > self.max_replans:
                    return self._fail(
                        ExecutionResult.failure(
                            "Execution failed: exceeded retry_execute limit.",
                            next_action="abort",
                        )
                    )
                continue

            if heal_result.ok and heal_result.next_action == "replan":
                planning_retry += 1
                execute_retry = 0
                continue

            if heal_result.ok and heal_result.next_action == "completed":
                self.state_machine.transition_to(RuntimeState.COMPLETED)
                return heal_result

            return self._fail(heal_result)

        return self._fail(
            ExecutionResult.failure("Execution failed: exceeded replan limit.", next_action="abort")
        )

    def _run_pipeline_once(
        self,
        *,
        query: str,
        registry_snapshot: RegistrySnapshot,
        planning_retry: int,
        context: OrchestrationContext,
    ) -> tuple[ExecutionResult, ExecutionResult, ExecutionResult]:
        """运行一轮 route->plan->execute pipeline。"""
        route_result: ExecutionResult = ExecutionResult.failure("Routing stage not executed.")
        plan_result: ExecutionResult = ExecutionResult.failure("Planning stage not executed.")
        execute_result: ExecutionResult = ExecutionResult.failure("Execution stage not executed.")

        async def route_stage(msg: Msg | list[Msg] | None) -> Msg:
            nonlocal route_result
            self.state_machine.transition_to(RuntimeState.ROUTING)
            route_result = self.router.route(query, registry_snapshot)
            self.metrics.record("routing.completed", success=route_result.ok)
            return _ensure_msg(msg)

        async def plan_stage(msg: Msg | list[Msg] | None) -> Msg:
            nonlocal plan_result
            if not route_result.ok:
                plan_result = ExecutionResult.failure("Planning skipped due to routing failure.")
                return _ensure_msg(msg)

            self.state_machine.transition_to(RuntimeState.PLANNING)
            plan_result = self.planner.plan(query, route_result.data, retry=planning_retry)
            self.metrics.record("planning.completed", success=plan_result.ok, retry=planning_retry)
            return _ensure_msg(msg)

        async def execute_stage(msg: Msg | list[Msg] | None) -> Msg:
            nonlocal execute_result
            if not plan_result.ok:
                execute_result = ExecutionResult.failure("Execution skipped due to planning failure.")
                return _ensure_msg(msg)

            self.state_machine.transition_to(RuntimeState.EXECUTING)
            execute_result = self.executor.execute(query, plan_result.data)
            self.metrics.record("execution.completed", success=execute_result.ok)
            return _ensure_msg(msg)

        pipeline = SequentialPipeline(
            agents=[
                _StageAgent("stage-router", route_stage),
                _StageAgent("stage-planner", plan_stage),
                _StageAgent("stage-executor", execute_stage),
            ]
        )

        run_async(pipeline(Msg(name="user", role="user", content=query)))
        return route_result, plan_result, execute_result

    def _heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        """执行自愈。"""
        self.state_machine.transition_to(RuntimeState.HEALING)
        self.metrics.record("healing.triggered", attempt=attempt)
        heal_result = self.healer.heal(failed_result, context, attempt=attempt)
        if heal_result.ok:
            self.metrics.record("healing.success", action=heal_result.next_action or "none")
        else:
            self.metrics.record("healing.failed", error=heal_result.error or "unknown")
        return heal_result

    def _fail(self, result: ExecutionResult) -> ExecutionResult:
        """标记失败。"""
        if self.state_machine.state is not RuntimeState.FAILED:
            self.state_machine.transition_to(RuntimeState.FAILED)
        return result

    @staticmethod
    def _pick_failed_result(
        route_result: ExecutionResult,
        plan_result: ExecutionResult,
        execute_result: ExecutionResult,
    ) -> ExecutionResult:
        if not route_result.ok:
            return route_result
        if not plan_result.ok:
            return plan_result
        return execute_result


def _ensure_msg(msg: Msg | list[Msg] | None) -> Msg:
    """pipeline 过程中统一返回 Msg。"""
    if isinstance(msg, Msg):
        return msg
    if isinstance(msg, list) and msg:
        return msg[-1]
    return Msg(name="system", role="assistant", content="")
