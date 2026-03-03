# -*- coding: utf-8 -*-
"""
LLM 自愈模块。

包含：
- LLMFailureClassifier: 失败分类
- LLMSelfHealer: 自愈动作决策
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from pydantic import BaseModel, Field

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async
from orchestrator.interfaces import Healer, OrchestrationContext
from orchestrator.result import ExecutionResult


class FailureType(str, Enum):
    """失败类型。"""

    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    DEPENDENCY_FAILURE = "dependency_failure"
    EMPTY_RETRIEVAL = "empty_retrieval"
    PLANNING_FAILURE = "planning_failure"
    EXECUTION_FAILURE = "execution_failure"
    UNKNOWN = "unknown"


class FailureClassification(BaseModel):
    """失败分类结构化输出。"""

    failure_type: FailureType
    reason: str = ""


class HealingDecision(BaseModel):
    """自愈动作结构化输出。"""

    next_action: str = Field(description="retry_execute | replan | abort | completed")
    reason: str = Field(default="")


class LLMFailureClassifier:
    """LLM 失败分类器。"""

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        sys_prompt: str | None = None,
        max_iters: int = 3,
    ) -> None:
        self._factory = AgentScopeFactory(model_config=model_config)
        self._sys_prompt = sys_prompt or (
            "你是失败分类代理。请根据错误信息判断 failure_type。"
            "仅输出结构化结果。"
        )
        self._max_iters = max_iters
        self._agent: ReActAgent | None = None

    def classify(self, result: ExecutionResult) -> FailureType:
        """分类失败结果。"""
        try:
            payload = self._llm_classify(result)
            return payload.failure_type
        except Exception:
            return FailureType.UNKNOWN

    def _llm_classify(self, result: ExecutionResult) -> FailureClassification:
        agent = self._ensure_agent()
        user_msg = Msg(
            name="user",
            role="user",
            content=(
                "请进行失败分类。\n"
                f"error: {result.error}\n"
                f"next_action: {result.next_action}\n"
                f"data: {dict(result.data)}\n"
            ),
        )
        reply = run_async(agent(user_msg, structured_model=FailureClassification))
        metadata = getattr(reply, "metadata", None) or {}
        return FailureClassification.model_validate(metadata)

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent
        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="orchestrator_failure_classifier",
            sys_prompt=self._sys_prompt,
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._agent


class LLMSelfHealer(Healer):
    """LLM 自愈处理器。"""

    _ALLOWED_ACTIONS = {"retry_execute", "replan", "abort", "completed"}

    def __init__(
        self,
        classifier: LLMFailureClassifier,
        *,
        model_config: ModelConfig,
        max_rounds: int = 3,
        sys_prompt: str | None = None,
        max_iters: int = 3,
    ) -> None:
        self._classifier = classifier
        self._max_rounds = max(1, max_rounds)
        self._factory = AgentScopeFactory(model_config=model_config)
        self._sys_prompt = sys_prompt or (
            "你是自愈决策代理。根据失败类型、错误上下文和尝试次数给出下一步动作。"
            "仅输出结构化结果。"
        )
        self._max_iters = max_iters
        self._agent: ReActAgent | None = None

    def heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        """执行 LLM 自愈决策。"""
        if attempt >= self._max_rounds:
            return ExecutionResult.failure(
                "Healing failed: exceeded max healing rounds.",
                {"attempt": attempt},
                next_action="abort",
            )

        failure_type = self._classifier.classify(failed_result)

        try:
            decision = self._llm_heal(
                failed_result=failed_result,
                context=context,
                failure_type=failure_type,
                attempt=attempt,
            )
        except Exception as exc:
            return ExecutionResult.failure(
                f"Healing failed: {exc}",
                {"attempt": attempt, "failure_type": failure_type.value},
                next_action="abort",
            )

        if decision.next_action not in self._ALLOWED_ACTIONS:
            return ExecutionResult.failure(
                f"Healing failed: invalid action {decision.next_action}",
                {"attempt": attempt, "failure_type": failure_type.value},
                next_action="abort",
            )

        return ExecutionResult.success(
            {
                "attempt": attempt,
                "failure_type": failure_type.value,
                "reason": decision.reason,
            },
            next_action=decision.next_action,
        )

    def _llm_heal(
        self,
        *,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        failure_type: FailureType,
        attempt: int,
    ) -> HealingDecision:
        agent = self._ensure_agent()
        user_msg = Msg(
            name="user",
            role="user",
            content=(
                "请给出自愈动作。\n"
                f"attempt: {attempt}\n"
                f"failure_type: {failure_type.value}\n"
                f"error: {failed_result.error}\n"
                f"failed_data: {dict(failed_result.data)}\n"
                f"query: {context.query}\n"
                f"route_data: {dict(context.route_data or {})}\n"
                f"plan_data: {dict(context.plan_data or {})}\n"
            ),
        )
        reply = run_async(agent(user_msg, structured_model=HealingDecision))
        metadata = getattr(reply, "metadata", None) or {}
        return HealingDecision.model_validate(metadata)

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent
        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="orchestrator_self_healer",
            sys_prompt=self._sys_prompt,
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._agent
