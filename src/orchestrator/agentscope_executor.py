# -*- coding: utf-8 -*-
"""
AgentScope ReAct 执行器模块

该模块提供了基于 AgentScope 框架的 ReAct 执行器实现，
支持 OpenAI、DashScope 和 Ollama 等多种模型后端。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from config.model_config import ModelConfig
from orchestrator.result import ExecutionResult


@dataclass(slots=True, frozen=True)
class AgentScopeRuntimeConfig:
    """
    AgentScope 运行时配置数据类（兼容旧版本）
    
    存储执行器所需的配置信息，包括是否启用、提供商、模型名称和 API 密钥。
    推荐使用 ModelConfig 类代替。
    
    属性:
        enabled: 是否启用 AgentScope 执行器
        provider: 模型提供商（openai/dashscope/ollama）
        model_name: 模型名称
        api_key: API 密钥（可选）
    """
    enabled: bool  # 是否启用
    provider: str  # 模型提供商
    model_name: str  # 模型名称
    api_key: str | None  # API 密钥

    @classmethod
    def from_model_config(cls, config: ModelConfig) -> "AgentScopeRuntimeConfig":
        """
        从 ModelConfig 创建配置实例
        
        参数:
            config: ModelConfig 实例
            
        返回:
            AgentScopeRuntimeConfig 实例
        """
        return cls(
            enabled=config.enabled,
            provider=config.provider,
            model_name=config.model_name,
            api_key=config.api_key,
        )

    @classmethod
    def from_env(cls) -> "AgentScopeRuntimeConfig":
        """
        从环境变量创建配置实例（已废弃，建议使用配置文件）
        
        读取以下环境变量：
        - AGENTSCOPE_EXECUTOR_ENABLED: 是否启用
        - AGENTSCOPE_MODEL_PROVIDER: 模型提供商
        - AGENTSCOPE_MODEL_NAME: 模型名称
        - AGENTSCOPE_API_KEY / OPENAI_API_KEY: API 密钥
        
        返回:
            AgentScopeRuntimeConfig 实例
        """
        # 委托给 ModelConfig.from_env()
        model_config = ModelConfig.from_env()
        return cls.from_model_config(model_config)

    def is_usable(self) -> bool:
        """
        检查配置是否可用
        
        检查条件：
        - 已启用
        - Ollama 提供商或已配置 API 密钥
        
        返回:
            配置是否可用
        """
        if not self.enabled:
            return False
        # Ollama 不需要 API 密钥
        if self.provider == "ollama":
            return True
        return bool(self.api_key)


class AgentScopeReActExecutor:
    """
    AgentScope ReAct 执行器
    
    基于 AgentScope 框架的 ReAct（推理-行动）模式执行器。
    当 AgentScope 不可用时自动降级到回退执行器。
    
    属性:
        _fallback_executor: 回退执行器
        _model_config: 模型配置实例
        _sys_prompt: 系统提示词
        _max_iters: 最大迭代次数
        _agent: ReAct 代理实例
        _init_error: 初始化错误信息
    """
    def __init__(
        self,
        fallback_executor: Any,
        *,
        model_config: ModelConfig | None = None,
        runtime_config: AgentScopeRuntimeConfig | None = None,
        sys_prompt: str | None = None,
        max_iters: int = 5,
    ) -> None:
        """
        初始化 AgentScope ReAct 执行器
        
        参数:
            fallback_executor: 回退执行器，当 AgentScope 不可用时使用
            model_config: 模型配置实例（推荐）
            runtime_config: 运行时配置（兼容旧版本，不推荐）
            sys_prompt: 系统提示词（可选）
            max_iters: 最大迭代次数（可选，默认从配置读取）
        """
        self._fallback_executor = fallback_executor
        
        # 优先使用 model_config，其次兼容 runtime_config
        if model_config is not None:
            self._model_config = model_config
        elif runtime_config is not None:
            # 从 runtime_config 转换
            self._model_config = ModelConfig(
                enabled=runtime_config.enabled,
                provider=runtime_config.provider,
                model_name=runtime_config.model_name,
                api_key=runtime_config.api_key,
            )
        else:
            # 默认从环境变量创建（兼容旧版本）
            self._model_config = ModelConfig.from_env()
        
        # 系统提示词：优先参数，其次配置文件，最后默认值
        self._sys_prompt = sys_prompt or self._model_config.react.sys_prompt
        # 最大迭代次数：优先参数，其次配置文件，最后默认值
        self._max_iters = max_iters if max_iters != 5 else self._model_config.react.max_iters
        
        self._agent = None  # 延迟初始化
        self._init_error: str | None = None

    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        """
        执行任务
        
        使用 AgentScope ReAct 代理执行任务，失败时降级到回退执行器。
        
        参数:
            query: 用户查询字符串
            plan_data: 执行计划数据
            
        返回:
            执行结果
        """
        # 检查配置是否可用
        if not self._model_config.is_usable():
            result = self._fallback_executor.execute(query, plan_data)
            return self._mark_degraded(result, reason="agentscope_not_enabled_or_missing_credentials")

        # 确保代理已初始化
        if not self._ensure_agent():
            result = self._fallback_executor.execute(query, plan_data)
            return self._mark_degraded(result, reason=self._init_error or "agentscope_init_failed")

        try:
            from agentscope.message import Msg

            # 构建用户消息
            user_msg = Msg(
                name="user",
                role="user",
                content=self._build_execution_prompt(query, plan_data),
            )
            # 调用代理执行
            response = self._agent(user_msg)

            # 提取响应文本
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
            # 运行时错误，降级到回退执行器
            result = self._fallback_executor.execute(query, plan_data)
            reason = f"agentscope_runtime_error:{exc}"
            return self._mark_degraded(result, reason=reason)

    def _ensure_agent(self) -> bool:
        """
        确保代理已初始化
        
        延迟初始化 AgentScope ReAct 代理。
        
        返回:
            初始化是否成功
        """
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

            # 初始化 AgentScope
            init(project="adaptive-orchestrator", name="agentscope-react-executor")

            provider = self._model_config.provider
            model_name = self._model_config.model_name
            api_key = self._model_config.api_key
            provider_config = self._model_config.get_provider_config()

            # 根据提供商创建对应的模型和格式化器
            if provider == "openai":
                model_kwargs = {"model_name": model_name, "api_key": api_key, "stream": provider_config.stream}
                if provider_config.base_url:
                    model_kwargs["base_url"] = provider_config.base_url
                model = OpenAIChatModel(**model_kwargs)
                formatter = OpenAIChatFormatter()
            elif provider == "dashscope":
                model_kwargs = {"model_name": model_name, "api_key": api_key, "stream": provider_config.stream}
                if provider_config.base_url:
                    model_kwargs["base_url"] = provider_config.base_url
                model = DashScopeChatModel(**model_kwargs)
                formatter = DashScopeChatFormatter()
            elif provider == "ollama":
                model_kwargs = {"model_name": model_name, "stream": provider_config.stream}
                if provider_config.base_url:
                    model_kwargs["base_url"] = provider_config.base_url
                model = OllamaChatModel(**model_kwargs)
                formatter = OllamaChatFormatter()
            else:
                raise ValueError(f"Unsupported model provider: {provider}")

            # 创建 ReAct 代理
            self._agent = ReActAgent(
                name="adaptive_orchestrator_executor",
                sys_prompt=self._sys_prompt,
                model=model,
                formatter=formatter,
                max_iters=self._max_iters,
            )
            self._init_error = None
            return True
        except Exception as exc:
            self._init_error = str(exc)
            return False

    @staticmethod
    def _build_execution_prompt(query: str, plan_data: Mapping[str, Any]) -> str:
        """
        构建执行提示词
        
        将查询和计划数据格式化为可执行的提示词。
        
        参数:
            query: 用户查询字符串
            plan_data: 执行计划数据
            
        返回:
            格式化后的提示词
        """
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
        """
        标记结果为降级状态
        
        在结果数据中添加降级标记和原因。
        
        参数:
            result: 原始执行结果
            reason: 降级原因
            
        返回:
            标记后的执行结果
        """
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
