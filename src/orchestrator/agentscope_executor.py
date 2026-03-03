# -*- coding: utf-8 -*-
"""
AgentScope ReAct 执行器（无规则兜底）。

能力：
- 基于 LLM 执行计划
- 通过 Toolkit 调用 registry entrypoint
- 注册本地 Agent skills
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.tool import Toolkit

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async
from orchestrator.result import ExecutionResult


@dataclass(slots=True, frozen=True)
class AgentScopeRuntimeConfig:
    """兼容配置对象（用于历史兼容）。"""

    enabled: bool
    provider: str
    model_name: str
    api_key: str | None

    @classmethod
    def from_model_config(cls, config: ModelConfig) -> "AgentScopeRuntimeConfig":
        return cls(
            enabled=config.enabled,
            provider=config.provider,
            model_name=config.model_name,
            api_key=config.api_key,
        )

    @classmethod
    def from_env(cls) -> "AgentScopeRuntimeConfig":
        model_config = ModelConfig.from_env()
        return cls.from_model_config(model_config)

    def is_usable(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "ollama":
            return True
        return bool(self.api_key)


class AgentScopeReActExecutor:
    """严格 AgentScope 执行器。"""

    def __init__(
        self,
        *,
        model_config: ModelConfig | None = None,
        runtime_config: AgentScopeRuntimeConfig | None = None,
        sys_prompt: str | None = None,
        max_iters: int = 5,
        skills_root: str | Path = ".agents/skills",
    ) -> None:
        if model_config is not None:
            self._model_config = model_config
        elif runtime_config is not None:
            self._model_config = ModelConfig(
                enabled=runtime_config.enabled,
                provider=runtime_config.provider,
                model_name=runtime_config.model_name,
                api_key=runtime_config.api_key,
            )
        else:
            self._model_config = ModelConfig.from_env()

        self._factory = AgentScopeFactory(model_config=self._model_config)
        self._sys_prompt = sys_prompt or self._model_config.react.sys_prompt
        self._max_iters = max_iters if max_iters != 5 else self._model_config.react.max_iters
        self._skills_root = Path(skills_root)

        self._agent: ReActAgent | None = None
        self._candidate_index: dict[str, Mapping[str, Any]] = {}

    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        """执行计划，不做 fallback。"""
        try:
            self._factory.ensure_usable()
            self._candidate_index = self._build_candidate_index(plan_data)
            agent = self._ensure_agent()

            reply = run_async(
                agent(
                    Msg(
                        name="user",
                        role="user",
                        content=self._build_execution_prompt(query, plan_data),
                    )
                )
            )
            text = reply.get_text_content() or str(reply.content)
            return ExecutionResult.success(
                {
                    "answer": text,
                    "plan": dict(plan_data),
                    "executor": "agentscope-react",
                    "metadata": getattr(reply, "metadata", {}) or {},
                },
                next_action="completed",
            )
        except Exception as exc:
            return ExecutionResult.failure(
                f"Execution failed: {exc}",
                {
                    "plan": dict(plan_data),
                    "executor": "agentscope-react",
                },
            )

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent

        model, formatter = self._factory.create_model_and_formatter()
        toolkit = Toolkit()
        toolkit.register_tool_function(self._list_registry_entries)
        toolkit.register_tool_function(self._invoke_registry_entry)
        self._register_local_skills(toolkit)

        self._agent = ReActAgent(
            name="adaptive_orchestrator_executor",
            sys_prompt=self._sys_prompt,
            model=model,
            formatter=formatter,
            toolkit=toolkit,
            max_iters=self._max_iters,
        )
        return self._agent

    def _register_local_skills(self, toolkit: Toolkit) -> None:
        """注册本地 skills 到 AgentScope（作为智能体技能提示）。"""
        if not self._skills_root.exists() or not self._skills_root.is_dir():
            return

        for child in sorted(self._skills_root.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                toolkit.register_agent_skill(str(child))
            except Exception:
                # 技能声明不合法时跳过，不中断主流程。
                continue

    def _list_registry_entries(
        self,
        capability: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出可用 registry 条目（供 LLM 选用）。"""
        entries = list(self._candidate_index.values())
        if source:
            entries = [entry for entry in entries if str(entry.get("source")) == source]
        if capability:
            entries = [
                entry
                for entry in entries
                if capability in [str(cap) for cap in entry.get("capabilities", [])]
            ]

        result: list[dict[str, Any]] = []
        for entry in entries:
            result.append(
                {
                    "id": entry.get("id"),
                    "source": entry.get("source"),
                    "capabilities": list(entry.get("capabilities", [])),
                    "entrypoint": entry.get("entrypoint"),
                    "version": entry.get("version"),
                }
            )
        return result

    def _invoke_registry_entry(
        self,
        entry_id: str,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 registry entrypoint。"""
        if entry_id not in self._candidate_index:
            raise ValueError(f"Unknown registry entry id: {entry_id}")

        entry = self._candidate_index[entry_id]
        entrypoint = str(entry.get("entrypoint", "")).strip()
        if ":" not in entrypoint:
            raise ValueError(f"Invalid entrypoint for {entry_id}: {entrypoint}")

        module_name, func_name = entrypoint.split(":", 1)
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        if not callable(func):
            raise TypeError(f"Entrypoint is not callable: {entrypoint}")

        payload = {"task": task, "context": context or {}}
        value = func(payload)
        if inspect.isawaitable(value):
            value = run_async(value)

        return {
            "entry_id": entry_id,
            "entrypoint": entrypoint,
            "result": value,
        }

    @staticmethod
    def _build_candidate_index(plan_data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        entries = plan_data.get("candidate_entries", [])
        index: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            entry_id = str(entry.get("id", "")).strip()
            if entry_id:
                index[entry_id] = entry
        return index

    @staticmethod
    def _build_execution_prompt(query: str, plan_data: Mapping[str, Any]) -> str:
        steps = plan_data.get("steps", [])
        step_lines = []
        for step in steps:
            step_lines.append(
                f"- {step.get('id')}: {step.get('action')} (depends_on={step.get('depends_on', [])})"
            )
        steps_text = "\n".join(step_lines) if step_lines else "- no-steps"
        return (
            f"用户目标: {query}\n"
            "你可以使用工具 `list_registry_entries` 和 `invoke_registry_entry` 调度候选单元。\n"
            f"执行计划:\n{steps_text}\n"
            "请执行并给出最终结果。"
        )
