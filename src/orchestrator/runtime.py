# -*- coding: utf-8 -*-
"""
自适应编排运行时模块

该模块提供了编排运行时的核心实现，包括：
- RuleBasedExecutor: 基于规则的执行器（作为降级方案）
- AdaptiveOrchestratorRuntime: 自适应编排运行时
"""
from __future__ import annotations

from typing import Any, Mapping

from observability.metrics import MetricsCollector
from orchestrator.interfaces import Executor, Healer, OrchestrationContext, Planner, Router
from orchestrator.result import ExecutionResult
from orchestrator.state import RuntimeState, RuntimeStateMachine
from registry.schema import RegistrySnapshot


class RuleBasedExecutor:
    """
    基于规则的执行器
    
    当 AgentScope 执行器不可用时作为降级方案使用。
    根据查询中的关键字判断执行结果。
    """
    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        """
        执行任务
        
        根据查询中的关键字模拟不同的执行结果。
        
        参数:
            query: 用户查询字符串
            plan_data: 执行计划数据
            
        返回:
            执行结果
        """
        lowered = query.lower()
        # 模拟超时错误
        if "timeout" in lowered or "超时" in lowered:
            return ExecutionResult.failure(
                "Execution failed: timeout while calling tool.",
                {"plan": plan_data},
            )
        # 模拟依赖服务不可用错误
        if "dependency" in lowered or "依赖" in lowered:
            return ExecutionResult.failure(
                "Execution failed: dependency service unavailable.",
                {"plan": plan_data},
            )
        # 模拟工具错误
        if "tool_error" in lowered or "工具异常" in lowered:
            return ExecutionResult.failure(
                "Execution failed: tool error.",
                {"plan": plan_data},
            )

        # 正常执行返回成功结果
        response = {
            "answer": "任务已通过自适应编排链路执行完成。",
            "plan_steps": len(plan_data.get("steps", [])),
            "plan": plan_data,
        }
        return ExecutionResult.success(response, next_action="completed")


class AdaptiveOrchestratorRuntime:
    """
    自适应编排运行时
    
    编排系统的核心运行时，协调路由器、计划器、执行器和自愈器
    完成完整的编排流程。支持重试和自愈机制。
    
    属性:
        router: 路由器实例
        planner: 计划器实例
        executor: 执行器实例
        healer: 自愈器实例
        metrics: 指标收集器
        max_replans: 最大重计划次数
        state_machine: 状态机实例
    """
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
        """
        初始化自适应编排运行时
        
        参数:
            router: 路由器实例
            planner: 计划器实例
            executor: 执行器实例
            healer: 自愈器实例
            metrics: 指标收集器（可选）
            max_replans: 最大重计划次数
        """
        self.router = router
        self.planner = planner
        self.executor = executor
        self.healer = healer
        self.metrics = metrics or MetricsCollector()
        self.max_replans = max(0, max_replans)
        self.state_machine = RuntimeStateMachine()

    def run(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        """
        执行编排流程
        
        完整的编排流程：路由 -> 计划 -> 执行 -> 自愈（如果需要）
        
        参数:
            query: 用户查询字符串
            registry_snapshot: 注册表快照
            
        返回:
            编排执行结果
        """
        # 创建编排上下文
        context = OrchestrationContext(query=query, registry_snapshot=registry_snapshot)
        heal_attempt = 0  # 自愈尝试次数
        planning_retry = 0  # 重计划次数

        # 阶段1: 路由
        self.state_machine.transition_to(RuntimeState.ROUTING)
        route_result = self.router.route(query, registry_snapshot)
        self.metrics.record("routing.completed", scene=route_result.data.get("scene", "unknown"))
        if not route_result.ok:
            return self._fail(route_result)
        context.route_data = route_result.data

        # 阶段2: 计划和执行循环
        while planning_retry <= self.max_replans:
            # 计划阶段
            self.state_machine.transition_to(RuntimeState.PLANNING)
            plan_result = self.planner.plan(query, context.route_data or {}, retry=planning_retry)
            self.metrics.record("planning.completed", retry=planning_retry)

            # 计划失败时尝试自愈
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
            
            # 执行阶段
            while True:
                self.state_machine.transition_to(RuntimeState.EXECUTING)
                execute_result = self.executor.execute(query, context.plan_data or {})
                self.metrics.record("execution.completed", success=execute_result.ok)

                # 执行成功则返回
                if execute_result.ok:
                    self.state_machine.transition_to(RuntimeState.COMPLETED)
                    return execute_result

                # 执行失败时尝试自愈
                heal_result = self._heal(execute_result, context, attempt=heal_attempt)
                heal_attempt += 1
                
                # 根据自愈结果决定下一步
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
        """
        执行自愈处理
        
        参数:
            failed_result: 失败的执行结果
            context: 编排上下文
            attempt: 当前尝试次数
            
        返回:
            自愈处理结果
        """
        self.state_machine.transition_to(RuntimeState.HEALING)
        self.metrics.record("healing.triggered", attempt=attempt)
        heal_result = self.healer.heal(failed_result, context, attempt=attempt)
        if heal_result.ok:
            self.metrics.record("healing.success", action=heal_result.next_action or "none")
        else:
            self.metrics.record("healing.failed", error=heal_result.error or "unknown")
        return heal_result

    def _fail(self, result: ExecutionResult) -> ExecutionResult:
        """
        标记执行失败
        
        参数:
            result: 失败的执行结果
            
        返回:
            原始失败结果
        """
        if self.state_machine.state is not RuntimeState.FAILED:
            self.state_machine.transition_to(RuntimeState.FAILED)
        return result
