from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from orchestrator.result import ExecutionResult


@dataclass(slots=True, frozen=True)
class AgentScopeRuntimeConfig:
    enabled: bool
    provider: str
    model_name: str
    api_key: str | None

    @classmethod
    def from_env(cls) -> "AgentScopeRuntimeConfig":
        enabled_flag = os.getenv("AGENTSCOPE_EXECUTOR_ENABLED", "0").strip().lower()
        provider = os.getenv("AGENTSCOPE_MODEL_PROVIDER", "openai").strip().lower()
        model_name = os.getenv("AGENTSCOPE_MODEL_NAME", "gpt-4o-mini").strip()
        api_key = os.getenv("AGENTSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        return cls(
            enabled=enabled_flag in {"1", "true", "yes", "on"},
            provider=provider,
            model_name=model_name,
            api_key=api_key,
        )

    def is_usable(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "ollama":
            return True
        return bool(self.api_key)


class AgentScopeReActExecutor:
    def __init__(
        self,
        fallback_executor: Any,
        *,
        runtime_config: AgentScopeRuntimeConfig | None = None,
        sys_prompt: str | None = None,
    ) -> None:
        self._fallback_executor = fallback_executor
        self._runtime_config = runtime_config or AgentScopeRuntimeConfig.from_env()
        self._sys_prompt = sys_prompt or (
            "你是一个自适应编排执行代理。根据计划步骤执行任务并输出结构化结果。"
        )
        self._agent = None
        self._init_error: str | None = None

    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        if not self._runtime_config.is_usable():
            result = self._fallback_executor.execute(query, plan_data)
            return self._mark_degraded(result, reason="agentscope_not_enabled_or_missing_credentials")

        if not self._ensure_agent():
            result = self._fallback_executor.execute(query, plan_data)
            return self._mark_degraded(result, reason=self._init_error or "agentscope_init_failed")

        try:
            from agentscope.message import Msg

            user_msg = Msg(
                name="user",
                role="user",
                content=self._build_execution_prompt(query, plan_data),
            )
            response = self._agent(user_msg)

            text = ""
            if hasattr(response, "get_text_content"):
                text = response.get_text_content()
            if not text:
                text = str(getattr(response, "content", response))

            return ExecutionResult.success(
                {
                    "answer": text,
                    "plan": plan_data,
                    "executor": "agentscope-react",
                },
                next_action="completed",
            )
        except Exception as exc:
            result = self._fallback_executor.execute(query, plan_data)
            reason = f"agentscope_runtime_error:{exc}"
            return self._mark_degraded(result, reason=reason)

    def _ensure_agent(self) -> bool:
        if self._agent is not None:
            return True

        try:
            from agentscope import init
            from agentscope.agent import ReActAgent
            from agentscope.formatter import (
                DashScopeChatFormatter,
                OllamaChatFormatter,
                OpenAIChatFormatter,
            )
            from agentscope.model import DashScopeChatModel, OllamaChatModel, OpenAIChatModel

            init(project="adaptive-orchestrator", name="agentscope-react-executor")

            provider = self._runtime_config.provider
            model_name = self._runtime_config.model_name
            api_key = self._runtime_config.api_key

            if provider == "openai":
                model = OpenAIChatModel(model_name=model_name, api_key=api_key, stream=False)
                formatter = OpenAIChatFormatter()
            elif provider == "dashscope":
                model = DashScopeChatModel(model_name=model_name, api_key=api_key, stream=False)
                formatter = DashScopeChatFormatter()
            elif provider == "ollama":
                model = OllamaChatModel(model_name=model_name, stream=False)
                formatter = OllamaChatFormatter()
            else:
                raise ValueError(f"Unsupported AGENTSCOPE_MODEL_PROVIDER: {provider}")

            self._agent = ReActAgent(
                name="adaptive_orchestrator_executor",
                sys_prompt=self._sys_prompt,
                model=model,
                formatter=formatter,
                max_iters=5,
            )
            self._init_error = None
            return True
        except Exception as exc:
            self._init_error = str(exc)
            return False

    @staticmethod
    def _build_execution_prompt(query: str, plan_data: Mapping[str, Any]) -> str:
        step_lines = []
        for step in plan_data.get("steps", []):
            step_lines.append(
                f"- {step.get('id')}: {step.get('action')} (depends_on={step.get('depends_on', [])})"
            )
        steps_text = "\n".join(step_lines) if step_lines else "- no-steps"
        return (
            f"用户目标: {query}\n"
            f"执行计划:\n{steps_text}\n"
            "请基于计划执行并给出最终结果，必要时说明使用了哪些能力。"
        )

    @staticmethod
    def _mark_degraded(result: ExecutionResult, *, reason: str) -> ExecutionResult:
        merged = dict(result.data)
        merged["degraded"] = True
        merged["degrade_reason"] = reason
        merged.setdefault("executor", "rule-based")
        if result.ok:
            return ExecutionResult.success(merged, next_action=result.next_action)
        return ExecutionResult.failure(
            result.error or reason,
            merged,
            next_action=result.next_action,
        )
