# -*- coding: utf-8 -*-
"""
注册表配置加载模块

该模块提供了从 YAML 文件加载注册表快照的功能。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from registry.schema import RegistrySnapshot, SchemaValidationError, parse_registry_payload


def load_registry_snapshot(
    agents_registry_path: str | Path,
    skills_registry_path: str | Path,
) -> RegistrySnapshot:
    """
    加载注册表快照
    
    从指定的代理和技能注册表 YAML 文件加载完整的注册表快照。
    验证两个文件的模式版本一致性。
    
    参数:
        agents_registry_path: 代理注册表文件路径
        skills_registry_path: 技能注册表文件路径
        
    返回:
        RegistrySnapshot 实例
        
    抛出:
        FileNotFoundError: 当文件不存在时
        SchemaValidationError: 当数据不符合模式要求或版本不一致时
    """
    agents_path = Path(agents_registry_path)
    skills_path = Path(skills_registry_path)

    # 读取 YAML 文件
    agents_payload = _read_yaml(agents_path)
    skills_payload = _read_yaml(skills_path)

    # 解析代理注册表
    agents_version, agents = parse_registry_payload(
        agents_payload,
        source="agent",
        source_path=str(agents_path),
    )
    # 解析技能注册表
    skills_version, skills = parse_registry_payload(
        skills_payload,
        source="skill",
        source_path=str(skills_path),
    )

    # 验证版本一致性
    if agents_version != skills_version:
        raise SchemaValidationError(
            f"schema_version mismatch: agents={agents_version}, skills={skills_version}"
        )

    return RegistrySnapshot(schema_version=agents_version, agents=agents, skills=skills)


def _read_yaml(path: Path) -> Mapping[str, Any]:
    """
    读取 YAML 文件
    
    安全地读取并解析 YAML 文件内容。
    
    参数:
        path: 文件路径
        
    返回:
        解析后的字典数据
        
    抛出:
        FileNotFoundError: 当文件不存在时
        SchemaValidationError: 当 YAML 根不是字典时
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing registry file: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(f"{path}: YAML root must be a mapping")
    return payload
