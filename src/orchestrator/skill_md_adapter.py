# -*- coding: utf-8 -*-
"""SKILL.md 统一执行适配器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscope.agent import ReActAgent
from agentscope.message import Msg

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async


@dataclass(slots=True)
class SkillMarkdownAdapter:
    """将 SKILL.md 内容映射为可执行 AgentScope 调用。"""

    model_config: ModelConfig
    max_iters: int = 3
    _factory: AgentScopeFactory = field(init=False, repr=False)
    _agent: ReActAgent | None = field(default=None, init=False, repr=False)
    _cache: dict[str, tuple[int, str]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._factory = AgentScopeFactory(model_config=self.model_config)

    def execute(self, *, skill_md: Path, task: str, context: dict[str, Any]) -> dict[str, Any]:
        skill_text = self._read_skill(skill_md)
        agent = self._ensure_agent()
        prompt = (
            "你正在执行一个 SKILL.md 规范任务。\n"
            f"技能文件路径: {skill_md}\n"
            f"技能内容:\n{skill_text}\n\n"
            f"用户任务: {task}\n"
            f"上下文: {context}\n\n"
            "请严格依据技能说明完成任务，并输出结果。"
        )
        reply = run_async(agent(Msg(name="user", role="user", content=prompt)))
        text = reply.get_text_content() or str(reply.content)
        return {"answer": text, "metadata": getattr(reply, "metadata", {}) or {}}

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent
        self._factory.ensure_usable()
        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="skill_markdown_adapter",
            sys_prompt="你是 skill 执行代理，请遵循输入的 SKILL.md 指令。",
            model=model,
            formatter=formatter,
            max_iters=self.max_iters,
        )
        return self._agent

    def _read_skill(self, path: Path) -> str:
        abs_path = path.resolve()
        stat = abs_path.stat()
        cache_key = str(abs_path)
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == stat.st_mtime_ns:
            return cached[1]
        text = abs_path.read_text(encoding="utf-8")
        self._cache[cache_key] = (stat.st_mtime_ns, text)
        return text
