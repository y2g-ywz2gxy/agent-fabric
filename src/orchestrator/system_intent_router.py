# -*- coding: utf-8 -*-
"""系统意图识别（如查询已集成能力）。"""
from __future__ import annotations

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from pydantic import BaseModel, Field

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async


class SystemIntentDecision(BaseModel):
    """系统意图结构化结果。"""

    intent: str = Field(description="list_integrations | none")
    reasoning: str = Field(default="", description="判定理由")


class SystemIntentRouter:
    """基于 LLM 的系统命令意图识别。"""

    def __init__(self, model_config: ModelConfig, *, max_iters: int = 2) -> None:
        self._factory = AgentScopeFactory(model_config=model_config)
        self._max_iters = max_iters
        self._agent: ReActAgent | None = None

    def detect(self, query: str) -> SystemIntentDecision:
        text = query.strip()
        if not text:
            return SystemIntentDecision(intent="none", reasoning="empty query")
        if not self._factory.model_config.is_usable():
            return SystemIntentDecision(intent="none", reasoning="model unavailable")
        try:
            agent = self._ensure_agent()
            msg = Msg(
                name="user",
                role="user",
                content=(
                    "判断用户消息是否在请求“查看主Agent已集成的agent/skill能力列表”。\n"
                    "仅输出 intent=list_integrations 或 none。\n"
                    "示例命中：\n"
                    "- 查看主agent集成了哪些能力\n"
                    "- 列出已集成的skills和agents\n"
                    "示例不命中：\n"
                    "- 注册一个skill\n"
                    "- 做市场分析\n"
                    f"用户消息：{text}"
                ),
            )
            reply = run_async(agent(msg, structured_model=SystemIntentDecision))
            metadata = getattr(reply, "metadata", None) or {}
            decision = SystemIntentDecision.model_validate(metadata)
            if decision.intent not in {"list_integrations", "none"}:
                return SystemIntentDecision(intent="none", reasoning="invalid intent fallback")
            return decision
        except Exception as exc:
            return SystemIntentDecision(intent="none", reasoning=f"intent detect failed: {exc}")

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent
        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="system_intent_router",
            sys_prompt="你是系统意图分类器。只输出结构化分类结果。",
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._agent
