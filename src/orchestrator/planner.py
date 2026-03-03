# -*- coding: utf-8 -*-
"""
自适应计划器模块

该模块提供了自适应执行计划生成器，负责根据路由结果
生成包含多个步骤的执行计划。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from orchestrator.result import ExecutionResult

# 尝试导入 AgentScope 的计划模块（可选依赖）
try:
    from agentscope.plan import Plan, SubTask
except ImportError:  # pragma: no cover - optional dependency path
    Plan = None
    SubTask = None


@dataclass(slots=True)
class PlanStep:
    """
    计划步骤数据类
    
    表示执行计划中的单个步骤。
    
    属性:
        id: 步骤标识符
        action: 动作类型
        depends_on: 依赖的其他步骤 ID 列表
        candidates: 候选执行单元列表
    """
    id: str  # 步骤 ID
    action: str  # 动作类型
    depends_on: list[str]  # 依赖步骤
    candidates: list[str]  # 候选执行单元


class AdaptivePlanner:
    """
    自适应计划器
    
    根据路由结果生成执行计划。支持模拟失败（用于测试）
    和 AgentScope 集成的计划生成。
    
    属性:
        _fail_first_n: 前N次计划模拟失败的次数（用于测试）
        _attempt: 当前尝试次数
    """
    def __init__(self, fail_first_n: int = 0) -> None:
        """
        初始化自适应计划器
        
        参数:
            fail_first_n: 前N次计划模拟失败（用于测试重试逻辑）
        """
        self._fail_first_n = max(0, fail_first_n)
        self._attempt = 0

    def plan(
        self,
        query: str,
        route_data: Mapping[str, Any],
        *,
        retry: int = 0,
    ) -> ExecutionResult:
        """
        生成执行计划
        
        根据查询和路由数据生成包含多个步骤的执行计划。
        
        参数:
            query: 用户查询字符串
            route_data: 路由数据
            retry: 重试次数
            
        返回:
            包含执行计划的执行结果
        """
        self._attempt += 1
        # 模拟失败（用于测试）
        if self._attempt <= self._fail_first_n:
            return ExecutionResult.failure(
                "Planning failed: simulated planning failure.",
                {"retry": retry},
                next_action="replan",
            )

        # 提取能力和候选
        capabilities = list(
            route_data.get("matched_capabilities")
            or route_data.get("required_capabilities")
            or []
        )
        candidates = [candidate["id"] for candidate in route_data.get("candidates", [])]

        # 检查是否有可用能力
        if not capabilities:
            return ExecutionResult.failure(
                "Planning failed: no capabilities available.",
                {"retry": retry},
                next_action="replan",
            )

        # 构建执行步骤
        steps, agentscope_plan = self._build_steps(query, candidates)

        # 构建返回结果
        payload = {
            "steps": [asdict(step) for step in steps],  # 步骤列表
            "dependencies": {step.id: step.depends_on for step in steps},  # 依赖关系
            "candidate_units": candidates,  # 候选执行单元
            "capabilities": capabilities,  # 所需能力
            "retry": retry,  # 重试次数
            "agentscope_plan": agentscope_plan,  # AgentScope 计划（如果可用）
        }
        return ExecutionResult.success(payload, next_action="execute")

    def _build_steps(
        self,
        query: str,
        candidates: list[str],
    ) -> tuple[list[PlanStep], dict[str, Any]]:
        """
        构建执行步骤
        
        根据是否可用 AgentScope 生成不同格式的执行步骤。
        
        参数:
            query: 用户查询字符串
            candidates: 候选执行单元列表
            
        返回:
            元组包含步骤列表和 AgentScope 计划
        """
        # 如果 AgentScope 不可用，使用内置的计划逻辑
        if Plan is None or SubTask is None:
            steps = [
                PlanStep(
                    id="step-route-context",
                    action="collect_context",
                    depends_on=[],
                    candidates=candidates,
                ),
                PlanStep(
                    id="step-retrieve-knowledge",
                    action="retrieve_knowledge",
                    depends_on=["step-route-context"],
                    candidates=[cid for cid in candidates if cid],
                ),
                PlanStep(
                    id="step-execute-goal",
                    action=f"execute_goal:{query[:40]}",
                    depends_on=["step-retrieve-knowledge"],
                    candidates=[cid for cid in candidates if cid],
                ),
            ]
            return steps, {"provider": "internal-fallback"}

        # 使用 AgentScope 的计划模块
        plan = Plan(
            name="Adaptive Execution Plan",
            description=f"针对用户目标构建编排执行计划：{query[:80]}",
            expected_outcome="完成任务并返回可用结果",
            subtasks=[
                SubTask(
                    name="Collect Context",
                    description="收集路由命中能力与上下文信息",
                    expected_outcome="形成可执行上下文",
                ),
                SubTask(
                    name="Retrieve Knowledge",
                    description="触发检索链路获取外部知识",
                    expected_outcome="得到可消费检索结果",
                ),
                SubTask(
                    name="Execute Goal",
                    description="执行目标任务并汇总输出",
                    expected_outcome="返回面向用户的最终答案",
                ),
            ],
        )

        # 将 AgentScope 的子任务转换为计划步骤
        steps: list[PlanStep] = []
        for idx, subtask in enumerate(plan.subtasks):
            step_id = f"step-{idx + 1:02d}"
            depends_on = [] if idx == 0 else [f"step-{idx:02d}"]
            steps.append(
                PlanStep(
                    id=step_id,
                    action=subtask.name.lower().replace(" ", "_"),
                    depends_on=depends_on,
                    candidates=[cid for cid in candidates if cid],
                ),
            )

        return steps, plan.model_dump()
