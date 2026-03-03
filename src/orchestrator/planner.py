# -*- coding: utf-8 -*-
"""
LLM 计划器模块。

基于 AgentScope + ReActAgent 生成结构化计划，落到 AgentScope Plan 数据结构。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.plan import Plan, SubTask
from pydantic import BaseModel, Field

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async
from orchestrator.result import ExecutionResult


@dataclass(slots=True)
class PlanStep:
    """执行计划中的步骤。"""

    id: str
    action: str
    depends_on: list[str]
    candidates: list[str]


class PlanTaskDecision(BaseModel):
    """单个任务决策。"""

    name: str = Field(description="子任务名称")
    description: str = Field(description="子任务说明")
    expected_outcome: str = Field(description="子任务预期产出")
    depends_on: list[int] = Field(
        default_factory=list,
        description="依赖的前置任务序号（从 1 开始）",
    )


class PlanDecision(BaseModel):
    """计划决策结构化输出。"""

    name: str = Field(description="计划名称")
    description: str = Field(description="计划描述")
    expected_outcome: str = Field(description="计划预期结果")
    tasks: list[PlanTaskDecision] = Field(description="有序任务列表")
    reasoning: str = Field(default="", description="简要推理")


class AgentScopePlanner:
    """基于 LLM 的计划器。"""

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        sys_prompt: str | None = None,
        max_iters: int = 4,
    ) -> None:
        self._factory = AgentScopeFactory(model_config=model_config)
        self._sys_prompt = sys_prompt or (
            "你是编排计划代理。请根据 query 和 route 数据，将目标拆分为可执行的顺序子任务。"
            "仅输出结构化结果。"
        )
        self._max_iters = max_iters
        self._agent: ReActAgent | None = None

    def plan(
        self,
        query: str,
        route_data: Mapping[str, Any],
        *,
        retry: int = 0,
    ) -> ExecutionResult:
        """生成执行计划。"""
        capabilities = list(
            route_data.get("matched_capabilities")
            or route_data.get("required_capabilities")
            or []
        )
        if not capabilities:
            return ExecutionResult.failure(
                "Planning failed: no capabilities available.",
                {"retry": retry},
                next_action="replan",
            )

        candidates = [candidate.get("id", "") for candidate in route_data.get("candidates", [])]
        candidates = [candidate for candidate in candidates if candidate]

        try:
            decision = self._llm_plan(query, route_data)
            steps, agentscope_plan = self._to_steps_and_plan(decision, candidates)
        except Exception as exc:
            return ExecutionResult.failure(
                f"Planning failed: {exc}",
                {"retry": retry},
                next_action="replan",
            )

        if not steps:
            return ExecutionResult.failure(
                "Planning failed: empty steps.",
                {"retry": retry},
                next_action="replan",
            )

        payload = {
            "steps": [asdict(step) for step in steps],
            "dependencies": {step.id: step.depends_on for step in steps},
            "candidate_units": candidates,
            "capabilities": capabilities,
            "retry": retry,
            "agentscope_plan": agentscope_plan,
            "llm_reasoning": decision.reasoning,
        }
        return ExecutionResult.success(payload, next_action="execute")

    def _llm_plan(self, query: str, route_data: Mapping[str, Any]) -> PlanDecision:
        """调用 LLM 生成计划。"""
        agent = self._ensure_agent()
        user_msg = Msg(
            name="user",
            role="user",
            content=(
                "请生成执行计划。\n"
                f"query:\n{query}\n\n"
                f"route_data:\n{dict(route_data)}\n\n"
                "要求:\n"
                "1. tasks 保持顺序可执行；\n"
                "2. depends_on 使用 1-based index；\n"
                "3. 子任务要具体、可验证。"
            ),
        )
        reply = run_async(agent(user_msg, structured_model=PlanDecision))
        metadata = getattr(reply, "metadata", None) or {}
        return PlanDecision.model_validate(metadata)

    def _ensure_agent(self) -> ReActAgent:
        """延迟初始化 Planner Agent。"""
        if self._agent is not None:
            return self._agent

        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="orchestrator_planner",
            sys_prompt=self._sys_prompt,
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._agent

    @staticmethod
    def _to_steps_and_plan(
        decision: PlanDecision,
        candidates: list[str],
    ) -> tuple[list[PlanStep], dict[str, Any]]:
        """将 LLM 决策转换为步骤和 AgentScope Plan。"""
        if not decision.tasks:
            return [], {}

        subtasks: list[SubTask] = []
        steps: list[PlanStep] = []

        for idx, task in enumerate(decision.tasks):
            subtasks.append(
                SubTask(
                    name=task.name,
                    description=task.description,
                    expected_outcome=task.expected_outcome,
                )
            )

            step_id = f"step-{idx + 1:02d}"
            depends_on = [
                f"step-{dep:02d}"
                for dep in task.depends_on
                if 1 <= dep <= len(decision.tasks) and dep <= idx
            ]
            steps.append(
                PlanStep(
                    id=step_id,
                    action=task.name.lower().replace(" ", "_")[:64],
                    depends_on=depends_on,
                    candidates=list(candidates),
                )
            )

        plan = Plan(
            name=decision.name,
            description=decision.description,
            expected_outcome=decision.expected_outcome,
            subtasks=subtasks,
        )
        return steps, plan.model_dump()
