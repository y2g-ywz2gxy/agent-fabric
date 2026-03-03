# -*- coding: utf-8 -*-
"""
AgentScope 运行时共享能力。

包含：
- 模型与格式化器工厂
- 异步执行桥接
- JSONSession 会话状态管理
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscope import init
from agentscope.formatter import DashScopeChatFormatter, OllamaChatFormatter, OpenAIChatFormatter
from agentscope.model import DashScopeChatModel, OllamaChatModel, OpenAIChatModel
from agentscope.module import StateModule
from agentscope.session import JSONSession

from config.model_config import ModelConfig


_init_lock = threading.Lock()
_initialized = False


class AgentScopeRuntimeError(RuntimeError):
    """AgentScope 运行时错误。"""


@dataclass(slots=True)
class AgentScopeFactory:
    """AgentScope 模型/格式化器工厂。"""

    model_config: ModelConfig
    project: str = "adaptive-orchestrator"

    def ensure_usable(self) -> None:
        """校验模型配置是否可用，不可用直接抛错。"""
        if not self.model_config.is_usable():
            raise AgentScopeRuntimeError(
                "AgentScope is not usable: executor disabled or missing model credentials."
            )

    def create_model_and_formatter(self) -> tuple[Any, Any]:
        """创建模型与 formatter。"""
        self.ensure_usable()
        _ensure_agentscope_initialized(self.project)

        provider = self.model_config.provider
        provider_config = self.model_config.get_provider_config()

        if provider == "openai":
            client_kwargs: dict[str, Any] | None = None
            if provider_config.base_url:
                client_kwargs = {"base_url": provider_config.base_url}
            model = OpenAIChatModel(
                model_name=self.model_config.model_name,
                api_key=self.model_config.api_key,
                stream=provider_config.stream,
                client_kwargs=client_kwargs,
            )
            return model, OpenAIChatFormatter()

        if provider == "dashscope":
            model = DashScopeChatModel(
                model_name=self.model_config.model_name,
                api_key=self.model_config.api_key or "",
                stream=provider_config.stream,
            )
            return model, DashScopeChatFormatter()

        if provider == "ollama":
            model = OllamaChatModel(
                model_name=self.model_config.model_name,
                stream=provider_config.stream,
                host=provider_config.base_url,
            )
            return model, OllamaChatFormatter()

        raise AgentScopeRuntimeError(f"Unsupported model provider: {provider}")


@dataclass(slots=True)
class OrchestratorSessionState(StateModule):
    """可序列化的编排会话状态。"""

    turn_count: int = 0
    last_route_data: dict[str, Any] = field(default_factory=dict)
    last_plan_data: dict[str, Any] = field(default_factory=dict)
    last_state_history: list[str] = field(default_factory=list)
    conversation_trace: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        StateModule.__init__(self)
        self.register_state("turn_count")
        self.register_state("last_route_data")
        self.register_state("last_plan_data")
        self.register_state("last_state_history")
        self.register_state("conversation_trace")

    def record_turn(
        self,
        *,
        query: str,
        response: dict[str, Any],
        route_data: dict[str, Any],
        plan_data: dict[str, Any],
        state_history: list[str],
    ) -> None:
        """记录单轮会话摘要。"""
        self.turn_count += 1
        self.last_route_data = route_data
        self.last_plan_data = plan_data
        self.last_state_history = state_history
        self.conversation_trace.append(
            {
                "turn": self.turn_count,
                "query": query,
                "status": response.get("status"),
                "next_action": response.get("next_action"),
                "error": response.get("error"),
            }
        )


@dataclass(slots=True)
class JSONSessionStore:
    """基于 AgentScope JSONSession 的会话存储。"""

    session_id: str
    user_id: str = ""
    save_dir: Path = Path(".sessions")
    _session: JSONSession = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._session = JSONSession(save_dir=str(self.save_dir))

    def load(self, state: OrchestratorSessionState) -> None:
        """加载会话状态。"""
        run_async(
            self._session.load_session_state(
                self.session_id,
                user_id=self.user_id,
                allow_not_exist=True,
                orchestrator=state,
            )
        )

    def save(self, state: OrchestratorSessionState) -> None:
        """保存会话状态。"""
        run_async(
            self._session.save_session_state(
                self.session_id,
                user_id=self.user_id,
                orchestrator=state,
            )
        )


def _ensure_agentscope_initialized(project: str) -> None:
    """全局初始化 AgentScope（幂等保护）。"""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        init(project=project, name="orchestrator-runtime")
        _initialized = True


def run_async(coro: Any) -> Any:
    """在同步上下文中安全执行协程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive path
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return result.get("value")
