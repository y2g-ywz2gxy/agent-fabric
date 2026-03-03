# -*- coding: utf-8 -*-
"""
LLM 路由器模块。

基于 AgentScope + ReActAgent 对用户查询进行场景识别、能力匹配与候选单元选择。
"""
from __future__ import annotations

from typing import Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from pydantic import BaseModel, Field

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async
from orchestrator.result import ExecutionResult
from registry.schema import RegistryEntry, RegistrySnapshot


class RouteDecision(BaseModel):
    """路由决策结构化输出。"""

    scene: str = Field(description="识别的任务场景")
    required_capabilities: list[str] = Field(
        description="完成任务所需能力列表，使用注册表中已有 capability 名称"
    )
    candidate_ids: list[str] = Field(
        default_factory=list,
        description="建议执行的 agent/skill 的 registry entry id 列表",
    )
    reasoning: str = Field(default="", description="简要推理理由")


class AgentScopeRouter:
    """基于 LLM 的路由器。"""

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        sys_prompt: str | None = None,
        max_iters: int = 4,
    ) -> None:
        self._factory = AgentScopeFactory(model_config=model_config)
        self._sys_prompt = sys_prompt or (
            "你是编排路由代理。请根据用户目标与 registry 信息，输出场景、"
            "能力清单和候选 entry id。只输出结构化结果。"
        )
        self._max_iters = max_iters
        self._agent: ReActAgent | None = None

    def route(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        """执行 LLM 路由。"""
        normalized = query.strip()
        if not normalized:
            return ExecutionResult.failure("Routing failed: query is empty.")

        try:
            decision = self._llm_route(normalized, registry_snapshot)
        except Exception as exc:
            return ExecutionResult.failure(f"Routing failed: {exc}")

        required_capabilities = [c for c in decision.required_capabilities if c]
        candidate_entries = self._resolve_candidates(decision.candidate_ids, registry_snapshot)
        if not candidate_entries and required_capabilities:
            candidate_entries = list(registry_snapshot.find_by_capabilities(required_capabilities))

        required_set = set(required_capabilities)
        matched_capabilities = sorted(
            {
                capability
                for entry in candidate_entries
                for capability in entry.capabilities
                if capability in required_set
            }
        )

        payload = {
            "scene": decision.scene,
            "required_capabilities": required_capabilities,
            "matched_capabilities": matched_capabilities,
            "candidates": [self._entry_to_payload(entry) for entry in candidate_entries],
            "llm_reasoning": decision.reasoning,
        }
        return ExecutionResult.success(payload, next_action="plan")

    def _llm_route(self, query: str, registry_snapshot: RegistrySnapshot) -> RouteDecision:
        """调用 LLM 获取结构化路由决策。"""
        agent = self._ensure_agent()
        registry_text = self._registry_to_prompt(registry_snapshot)
        user_msg = Msg(
            name="user",
            role="user",
            content=(
                "请完成路由决策。\n"
                f"用户查询:\n{query}\n\n"
                "可用 registry:\n"
                f"{registry_text}\n"
                "要求:\n"
                "1. required_capabilities 只能使用 registry 中出现的能力名称；\n"
                "2. candidate_ids 尽量从 registry entry id 中选择；\n"
                "3. scene 使用简洁英文标识。"
            ),
        )
        reply = run_async(agent(user_msg, structured_model=RouteDecision))
        metadata = getattr(reply, "metadata", None) or {}
        return RouteDecision.model_validate(metadata)

    def _ensure_agent(self) -> ReActAgent:
        """延迟初始化路由 Agent。"""
        if self._agent is not None:
            return self._agent

        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="orchestrator_router",
            sys_prompt=self._sys_prompt,
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._agent

    @staticmethod
    def _resolve_candidates(ids: list[str], snapshot: RegistrySnapshot) -> list[RegistryEntry]:
        id_set = {entry_id for entry_id in ids if entry_id}
        if not id_set:
            return []
        return [entry for entry in snapshot.all_entries if entry.id in id_set]

    @staticmethod
    def _registry_to_prompt(snapshot: RegistrySnapshot) -> str:
        lines: list[str] = []
        for entry in snapshot.all_entries:
            lines.append(
                f"- id={entry.id}; source={entry.source}; origin={entry.origin}; "
                f"capabilities={list(entry.capabilities)}; description={entry.description}; "
                f"loader={entry.loader_kind}:{entry.loader_target}; version={entry.version}"
            )
        return "\n".join(lines) if lines else "(empty registry)"

    @staticmethod
    def _entry_to_payload(entry: RegistryEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "source": entry.source,
            "origin": entry.origin,
            "description": entry.description,
            "capabilities": list(entry.capabilities),
            "entrypoint": entry.entrypoint,
            "loader_kind": entry.loader_kind,
            "loader_target": entry.loader_target,
            "healthcheck": entry.healthcheck,
            "version": entry.version,
        }
