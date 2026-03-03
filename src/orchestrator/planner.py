from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from orchestrator.result import ExecutionResult

try:
    from agentscope.plan import Plan, SubTask
except ImportError:  # pragma: no cover - optional dependency path
    Plan = None
    SubTask = None


@dataclass(slots=True)
class PlanStep:
    id: str
    action: str
    depends_on: list[str]
    candidates: list[str]


class AdaptivePlanner:
    def __init__(self, fail_first_n: int = 0) -> None:
        self._fail_first_n = max(0, fail_first_n)
        self._attempt = 0

    def plan(
        self,
        query: str,
        route_data: Mapping[str, Any],
        *,
        retry: int = 0,
    ) -> ExecutionResult:
        self._attempt += 1
        if self._attempt <= self._fail_first_n:
            return ExecutionResult.failure(
                "Planning failed: simulated planning failure.",
                {"retry": retry},
                next_action="replan",
            )

        capabilities = list(
            route_data.get("matched_capabilities")
            or route_data.get("required_capabilities")
            or []
        )
        candidates = [candidate["id"] for candidate in route_data.get("candidates", [])]

        if not capabilities:
            return ExecutionResult.failure(
                "Planning failed: no capabilities available.",
                {"retry": retry},
                next_action="replan",
            )

        steps, agentscope_plan = self._build_steps(query, candidates)

        payload = {
            "steps": [asdict(step) for step in steps],
            "dependencies": {step.id: step.depends_on for step in steps},
            "candidate_units": candidates,
            "capabilities": capabilities,
            "retry": retry,
            "agentscope_plan": agentscope_plan,
        }
        return ExecutionResult.success(payload, next_action="execute")

    def _build_steps(
        self,
        query: str,
        candidates: list[str],
    ) -> tuple[list[PlanStep], dict[str, Any]]:
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
