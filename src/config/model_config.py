# -*- coding: utf-8 -*-
"""
模型配置加载模块

该模块提供了模型配置的加载和管理功能，支持：
- 从 YAML 文件加载配置
- 环境变量引用和覆盖
- 配置验证
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(slots=True)
class ReactConfig:
    """
    ReAct 代理配置数据类
    
    属性:
        max_iters: 最大迭代次数
        sys_prompt: 系统提示词
    """
    max_iters: int = 5  # 最大迭代次数
    sys_prompt: str = "你是一个自适应编排执行代理。根据计划步骤执行任务并输出结构化结果。"  # 系统提示词


@dataclass(slots=True)
class ProviderConfig:
    """
    提供商配置数据类
    
    属性:
        base_url: API 基础 URL
        stream: 是否启用流式输出
    """
    base_url: str | None = None  # API 基础 URL
    stream: bool = False  # 是否启用流式输出


@dataclass(slots=True)
class ModelConfig:
    """
    模型配置数据类
    
    存储执行器所需的完整配置信息。
    
    属性:
        schema_version: 配置模式版本
        enabled: 是否启用 AgentScope 执行器
        provider: 模型提供商（openai/dashscope/ollama）
        model_name: 模型名称
        api_key: API 密钥（可选，支持环境变量）
        react: ReAct 代理配置
        providers: 各提供商的特定配置
    """
    schema_version: str = "1.0"  # 配置模式版本
    enabled: bool = False  # 是否启用
    provider: str = "openai"  # 模型提供商
    model_name: str = "gpt-4o-mini"  # 模型名称
    api_key: str | None = None  # API 密钥
    react: ReactConfig = field(default_factory=ReactConfig)  # ReAct 配置
    providers: dict[str, ProviderConfig] = field(default_factory=dict)  # 提供商配置

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

    def get_provider_config(self) -> ProviderConfig:
        """
        获取当前提供商的配置
        
        返回:
            当前提供商的配置实例
        """
        return self.providers.get(self.provider, ProviderConfig())

    @classmethod
    def from_env(cls) -> "ModelConfig":
        """
        从环境变量创建配置实例（兼容旧版本）
        
        读取以下环境变量：
        - AGENTSCOPE_EXECUTOR_ENABLED: 是否启用
        - AGENTSCOPE_MODEL_PROVIDER: 模型提供商
        - AGENTSCOPE_MODEL_NAME: 模型名称
        - AGENTSCOPE_API_KEY / OPENAI_API_KEY: API 密钥
        
        返回:
            ModelConfig 实例
        """
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


class ModelConfigError(ValueError):
    """模型配置错误异常"""
    pass


def load_model_config(config_path: str | Path) -> ModelConfig:
    """
    从 YAML 文件加载模型配置
    
    支持环境变量引用，格式为 ${ENV_VAR} 或 ${ENV_VAR:-default}。
    
    参数:
        config_path: 配置文件路径
        
    返回:
        ModelConfig 实例
        
    抛出:
        FileNotFoundError: 当配置文件不存在时
        ModelConfigError: 当配置格式错误时
    """
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Model config file not found: {path}")
    
    # 读取 YAML 文件
    raw_content = path.read_text(encoding="utf-8")
    
    # 解析环境变量引用
    resolved_content = _resolve_env_vars(raw_content)
    
    # 解析 YAML
    try:
        payload = yaml.safe_load(resolved_content)
    except yaml.YAMLError as exc:
        raise ModelConfigError(f"Invalid YAML in {path}: {exc}") from exc
    
    if payload is None:
        payload = {}
    
    if not isinstance(payload, Mapping):
        raise ModelConfigError(f"{path}: config root must be a mapping")
    
    return _parse_model_config(payload)


def _resolve_env_vars(content: str) -> str:
    """
    解析内容中的环境变量引用
    
    支持格式：
    - ${ENV_VAR}: 引用环境变量
    - ${ENV_VAR:-default}: 引用环境变量，不存在时使用默认值
    
    参数:
        content: 原始内容
        
    返回:
        解析后的内容
    """
    pattern = re.compile(r'\$\{([^}:]+)(?::-([^}]*))?\}')
    
    def replace(match: re.Match) -> str:
        env_var = match.group(1)
        default = match.group(2)
        
        value = os.getenv(env_var)
        if value is not None:
            return value
        if default is not None:
            return default
        return match.group(0)  # 保持原样
    
    return pattern.sub(replace, content)


def _parse_model_config(payload: Mapping[str, Any]) -> ModelConfig:
    """
    解析模型配置载荷
    
    参数:
        payload: YAML 解析后的字典数据
        
    返回:
        ModelConfig 实例
    """
    schema_version = str(payload.get("schema_version", "1.0"))
    
    # 解析 executor 配置
    executor_payload = payload.get("executor", {})
    if not isinstance(executor_payload, Mapping):
        executor_payload = {}
    
    enabled = bool(executor_payload.get("enabled", False))
    provider = str(executor_payload.get("provider", "openai")).lower()
    model_name = str(executor_payload.get("model_name", "gpt-4o-mini"))
    
    # API 密钥：优先从环境变量获取，其次使用配置文件
    api_key = os.getenv("AGENTSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    if api_key is None:
        api_key = executor_payload.get("api_key")
        if api_key is not None:
            api_key = str(api_key)
    
    # 解析 ReAct 配置
    react_payload = executor_payload.get("react", {})
    if not isinstance(react_payload, Mapping):
        react_payload = {}
    
    react_config = ReactConfig(
        max_iters=int(react_payload.get("max_iters", 5)),
        sys_prompt=str(react_payload.get("sys_prompt", ReactConfig.sys_prompt)),
    )
    
    # 解析各提供商配置
    providers_payload = payload.get("providers", {})
    if not isinstance(providers_payload, Mapping):
        providers_payload = {}
    
    providers: dict[str, ProviderConfig] = {}
    for provider_name, provider_config in providers_payload.items():
        if isinstance(provider_config, Mapping):
            providers[str(provider_name)] = ProviderConfig(
                base_url=provider_config.get("base_url"),
                stream=bool(provider_config.get("stream", False)),
            )
    
    return ModelConfig(
        schema_version=schema_version,
        enabled=enabled,
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        react=react_config,
        providers=providers,
    )
