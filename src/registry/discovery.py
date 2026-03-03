# -*- coding: utf-8 -*-
"""动态发现 agent/skill 文件并构建 registry entry。"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from registry.schema import SchemaValidationError, parse_registry_entry


def slugify(value: str) -> str:
    """将字符串转为稳定 id。"""
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    text = text.strip("-")
    return text or "unnamed"


def parse_skill_frontmatter(skill_md: Path) -> dict[str, Any]:
    """解析 SKILL.md frontmatter。"""
    if not skill_md.exists():
        raise FileNotFoundError(f"skill file not found: {skill_md}")
    raw = skill_md.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise SchemaValidationError(f"{skill_md}: missing YAML frontmatter")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise SchemaValidationError(f"{skill_md}: invalid YAML frontmatter")
    payload = yaml.safe_load(parts[1]) or {}
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(f"{skill_md}: frontmatter must be mapping")
    return dict(payload)


def extract_agent_meta(py_file: Path) -> dict[str, Any]:
    """从 agent python 文件提取 AGENT_META 和 run 函数。"""
    if not py_file.exists():
        raise FileNotFoundError(f"agent file not found: {py_file}")
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

    has_run = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
        for node in tree.body
    )
    if not has_run:
        raise SchemaValidationError(f"{py_file}: missing run(payload) function")

    meta_value: dict[str, Any] | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "AGENT_META":
            literal = ast.literal_eval(node.value)
            if not isinstance(literal, Mapping):
                raise SchemaValidationError(f"{py_file}: AGENT_META must be a mapping")
            meta_value = dict(literal)
            break

    if meta_value is None:
        raise SchemaValidationError(f"{py_file}: missing AGENT_META constant")
    return meta_value


def build_skill_entry_payload(skill_md: Path) -> dict[str, Any]:
    """基于 SKILL.md 构建 skill registry entry。"""
    frontmatter = parse_skill_frontmatter(skill_md)
    name = str(frontmatter.get("name", "")).strip()
    skill_id = slugify(name or skill_md.parent.name)
    description = str(frontmatter.get("description", "")).strip() or f"skill:{skill_id}"

    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    capabilities_raw = metadata.get("capabilities", [])
    if isinstance(capabilities_raw, str):
        capabilities = [capabilities_raw]
    elif isinstance(capabilities_raw, list):
        capabilities = [str(item).strip() for item in capabilities_raw if str(item).strip()]
    else:
        capabilities = []
    if not capabilities:
        capabilities = [f"skill.{skill_id}"]

    dependencies_raw = metadata.get("dependencies", [])
    if isinstance(dependencies_raw, str):
        dependencies = [dependencies_raw]
    elif isinstance(dependencies_raw, list):
        dependencies = [str(item).strip() for item in dependencies_raw if str(item).strip()]
    else:
        dependencies = []

    version = str(metadata.get("version", "0.1.0")).strip() or "0.1.0"

    payload = {
        "id": skill_id,
        "description": description,
        "capabilities": capabilities,
        "entrypoint": str(skill_md.resolve()),
        "loader_kind": "skill_md",
        "loader_target": str(skill_md.resolve()),
        "dependencies": dependencies,
        "healthcheck": f"skill-md:{skill_id}",
        "version": version,
        "origin": "dynamic",
    }
    parsed = parse_registry_entry(payload, source="skill", source_path=str(skill_md))
    return entry_to_payload(parsed)


def build_agent_entry_payload(py_file: Path) -> dict[str, Any]:
    """基于 agent 文件构建 agent registry entry。"""
    meta = extract_agent_meta(py_file)
    agent_id = str(meta.get("id", "")).strip() or slugify(py_file.stem)
    description = str(meta.get("description", "")).strip() or f"agent:{agent_id}"

    capabilities_raw = meta.get("capabilities", [])
    if isinstance(capabilities_raw, str):
        capabilities = [capabilities_raw]
    elif isinstance(capabilities_raw, list):
        capabilities = [str(item).strip() for item in capabilities_raw if str(item).strip()]
    else:
        capabilities = []
    if not capabilities:
        raise SchemaValidationError(f"{py_file}: AGENT_META.capabilities must be non-empty")

    dependencies_raw = meta.get("dependencies", [])
    if isinstance(dependencies_raw, str):
        dependencies = [dependencies_raw]
    elif isinstance(dependencies_raw, list):
        dependencies = [str(item).strip() for item in dependencies_raw if str(item).strip()]
    else:
        dependencies = []

    version = str(meta.get("version", "0.1.0")).strip() or "0.1.0"
    healthcheck = str(meta.get("healthcheck", f"python {py_file.name} --healthcheck")).strip()
    if not healthcheck:
        healthcheck = f"python {py_file.name} --healthcheck"

    loader_target = f"{py_file.resolve()}:run"
    payload = {
        "id": agent_id,
        "description": description,
        "capabilities": capabilities,
        "entrypoint": loader_target,
        "loader_kind": "python_file",
        "loader_target": loader_target,
        "dependencies": dependencies,
        "healthcheck": healthcheck,
        "version": version,
        "origin": "dynamic",
    }
    parsed = parse_registry_entry(payload, source="agent", source_path=str(py_file))
    return entry_to_payload(parsed)


def entry_to_payload(entry) -> dict[str, Any]:
    """RegistryEntry -> plain dict payload。"""
    return {
        "id": entry.id,
        "description": entry.description,
        "capabilities": list(entry.capabilities),
        "entrypoint": entry.entrypoint,
        "loader_kind": entry.loader_kind,
        "loader_target": entry.loader_target,
        "dependencies": list(entry.dependencies),
        "healthcheck": entry.healthcheck,
        "version": entry.version,
        "origin": entry.origin,
    }
