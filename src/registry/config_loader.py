# -*- coding: utf-8 -*-
"""
注册表配置加载模块

该模块提供了从 YAML 文件加载注册表快照的功能。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from registry.schema import (
    RegistryEntry,
    RegistrySnapshot,
    SchemaValidationError,
    ensure_unique_entry_ids,
    parse_registry_entry,
    parse_registry_payload,
)


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

    # 解析代理与技能注册表（兼容 entries 与 entry_files）
    agents_version, agents = _load_entries_from_registry(
        agents_path,
        source="agent",
    )
    skills_version, skills = _load_entries_from_registry(
        skills_path,
        source="skill",
    )

    # 验证版本一致性
    if agents_version != skills_version:
        raise SchemaValidationError(
            f"schema_version mismatch: agents={agents_version}, skills={skills_version}"
        )

    # 源内唯一 + 全局唯一
    ensure_unique_entry_ids(agents, scope=str(agents_path))
    ensure_unique_entry_ids(skills, scope=str(skills_path))
    ensure_unique_entry_ids(agents + skills, scope="global")

    return RegistrySnapshot(schema_version=agents_version, agents=agents, skills=skills)


def _load_entries_from_registry(path: Path, *, source: str) -> tuple[str, tuple[RegistryEntry, ...]]:
    payload = _read_yaml(path)

    # 兼容旧格式：registry.yaml 内联 entries
    if "entries" in payload:
        return parse_registry_payload(payload, source=source, source_path=str(path))

    # 新格式：registry.yaml 使用 entry_files 索引
    schema_version = payload.get("schema_version")
    if not schema_version:
        raise SchemaValidationError(f"{path}: schema_version is required")

    raw_entry_files = payload.get("entry_files")
    if not isinstance(raw_entry_files, list):
        raise SchemaValidationError(f"{path}: either entries or entry_files must be provided")

    entries: list[RegistryEntry] = []
    for index, raw in enumerate(raw_entry_files):
        if not isinstance(raw, str) or not raw.strip():
            raise SchemaValidationError(f"{path}:entry_files[{index}] must be a non-empty string")
        entry_path = (path.parent / raw).resolve()
        try:
            entry_path.relative_to(path.parent.resolve())
        except ValueError as exc:
            raise SchemaValidationError(
                f"{path}:entry_files[{index}] points outside registry directory"
            ) from exc

        entry_payload = _read_yaml(entry_path)
        entry_raw = entry_payload.get("entry") if "entry" in entry_payload else entry_payload
        entry = parse_registry_entry(
            entry_raw,
            source=source,
            source_path=str(entry_path),
        )
        entries.append(entry)

    return str(schema_version), tuple(entries)


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
