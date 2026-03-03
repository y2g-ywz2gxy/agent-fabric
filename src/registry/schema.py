# -*- coding: utf-8 -*-
"""
注册表模式定义模块

该模块定义了注册表的数据结构和验证逻辑，包括：
- SchemaValidationError: 模式验证错误异常
- RegistryEntry: 注册表条目数据类
- RegistrySnapshot: 注册表快照数据类
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


class SchemaValidationError(ValueError):
    """模式验证错误，当注册表数据不符合模式要求时抛出"""
    pass


@dataclass(slots=True, frozen=True)
class RegistryEntry:
    """
    注册表条目数据类
    
    表示注册表中的单个条目（代理或技能），包含其元数据信息。
    使用 frozen=True 确保不可变性。
    
    属性:
        id: 条目标识符
        capabilities: 提供的能力列表
        entrypoint: 入口点路径
        dependencies: 依赖列表
        healthcheck: 健康检查配置
        version: 版本号
        source: 来源类型（agent/skill）
    """
    id: str  # 条目 ID
    capabilities: tuple[str, ...]  # 能力列表
    entrypoint: str  # 入口点
    dependencies: tuple[str, ...]  # 依赖列表
    healthcheck: str  # 健康检查配置
    version: str  # 版本号
    source: str  # 来源类型


@dataclass(slots=True, frozen=True)
class RegistrySnapshot:
    """
    注册表快照数据类
    
    表示注册表在某个时刻的完整状态，包含所有代理和技能条目。
    使用 frozen=True 确保不可变性，支持线程安全读取。
    
    属性:
        schema_version: 模式版本号
        agents: 代理条目元组
        skills: 技能条目元组
        loaded_at: 加载时间戳
    """
    schema_version: str  # 模式版本
    agents: tuple[RegistryEntry, ...]  # 代理条目
    skills: tuple[RegistryEntry, ...]  # 技能条目
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))  # 加载时间

    @property
    def all_entries(self) -> tuple[RegistryEntry, ...]:
        """获取所有条目（代理 + 技能）"""
        return self.agents + self.skills

    def find_by_capabilities(self, capabilities: list[str] | tuple[str, ...]) -> tuple[RegistryEntry, ...]:
        """
        按能力查找条目
        
        返回具有指定能力中任意一个的所有条目。
        
        参数:
            capabilities: 所需能力列表
            
        返回:
            匹配的条目元组
        """
        wanted = set(capabilities)
        if not wanted:
            return tuple()
        matched = [
            entry
            for entry in self.all_entries
            if wanted.intersection(set(entry.capabilities))
        ]
        return tuple(matched)


def parse_registry_payload(
    payload: Mapping[str, Any],
    *,
    source: str,
    source_path: str,
) -> tuple[str, tuple[RegistryEntry, ...]]:
    """
    解析注册表载荷
    
    将 YAML 解析后的字典数据转换为模式版本和条目列表。
    
    参数:
        payload: YAML 解析后的字典数据
        source: 来源类型（agent/skill）
        source_path: 来源文件路径（用于错误信息）
        
    返回:
        元组包含模式版本和条目元组
        
    抛出:
        SchemaValidationError: 当数据不符合模式要求时
    """
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(f"{source_path}: payload must be a mapping")

    # 检查模式版本
    schema_version = payload.get("schema_version")
    if not schema_version:
        raise SchemaValidationError(f"{source_path}: schema_version is required")

    # 检查条目列表
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise SchemaValidationError(f"{source_path}: entries must be a list")

    # 解析每个条目
    entries: list[RegistryEntry] = []
    for index, raw in enumerate(raw_entries):
        entry_path = f"{source_path}:entries[{index}]"
        entries.append(_parse_entry(raw, source=source, source_path=entry_path))

    return str(schema_version), tuple(entries)


def _parse_entry(raw: Any, *, source: str, source_path: str) -> RegistryEntry:
    """
    解析单个注册表条目
    
    验证并转换单个条目的原始数据为 RegistryEntry。
    
    参数:
        raw: 原始条目数据
        source: 来源类型
        source_path: 来源路径（用于错误信息）
        
    返回:
        RegistryEntry 实例
        
    抛出:
        SchemaValidationError: 当数据不符合模式要求时
    """
    if not isinstance(raw, Mapping):
        raise SchemaValidationError(f"{source_path}: entry must be a mapping")

    # 检查必需字段
    required = ("id", "capabilities", "entrypoint", "dependencies", "healthcheck", "version")
    missing = [key for key in required if key not in raw]
    if missing:
        raise SchemaValidationError(f"{source_path}: missing required fields: {', '.join(missing)}")

    # 验证字段类型和内容
    capabilities = raw["capabilities"]
    dependencies = raw["dependencies"]
    if not isinstance(capabilities, list) or not capabilities:
        raise SchemaValidationError(f"{source_path}: capabilities must be a non-empty list")
    if not isinstance(dependencies, list):
        raise SchemaValidationError(f"{source_path}: dependencies must be a list")
    if not str(raw["healthcheck"]).strip():
        raise SchemaValidationError(f"{source_path}: healthcheck must be non-empty")
    if not str(raw["entrypoint"]).strip():
        raise SchemaValidationError(f"{source_path}: entrypoint must be non-empty")

    # 创建并返回条目实例
    return RegistryEntry(
        id=str(raw["id"]),
        capabilities=tuple(str(capability) for capability in capabilities),
        entrypoint=str(raw["entrypoint"]),
        dependencies=tuple(str(dependency) for dependency in dependencies),
        healthcheck=str(raw["healthcheck"]),
        version=str(raw["version"]),
        source=source,
    )
