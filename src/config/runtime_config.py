# -*- coding: utf-8 -*-
"""Runtime 配置加载模块。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(slots=True)
class SessionRuntimeConfig:
    """会话相关运行配置。"""

    resume_preview_turns: int = 5
    sessions_dir: str = ".sessions"


@dataclass(slots=True)
class ExecutionRuntimeConfig:
    """执行相关运行配置。"""

    max_parallel: int = 4
    fail_fast: bool = True


@dataclass(slots=True)
class RegistrationRuntimeConfig:
    """注册相关运行配置。"""

    audit_dir: str = "configs/audit"


@dataclass(slots=True)
class RuntimeConfig:
    """运行时配置。"""

    schema_version: str = "1.0"
    mode: str = "orchestrator_agent"
    output_format: str = "text_stream"
    session: SessionRuntimeConfig = field(default_factory=SessionRuntimeConfig)
    execution: ExecutionRuntimeConfig = field(default_factory=ExecutionRuntimeConfig)
    registration: RegistrationRuntimeConfig = field(default_factory=RegistrationRuntimeConfig)


class RuntimeConfigError(ValueError):
    """Runtime 配置错误。"""



def load_runtime_config(config_path: str | Path) -> RuntimeConfig:
    """从 YAML 文件加载运行时配置。"""
    path = Path(config_path)
    if not path.exists():
        return RuntimeConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise RuntimeConfigError(f"{path}: config root must be a mapping")

    return _parse_runtime_config(payload)



def _parse_runtime_config(payload: Mapping[str, Any]) -> RuntimeConfig:
    session_payload = payload.get("session", {})
    if not isinstance(session_payload, Mapping):
        session_payload = {}

    execution_payload = payload.get("execution", {})
    if not isinstance(execution_payload, Mapping):
        execution_payload = {}

    registration_payload = payload.get("registration", {})
    if not isinstance(registration_payload, Mapping):
        registration_payload = {}

    session = SessionRuntimeConfig(
        resume_preview_turns=max(0, int(session_payload.get("resume_preview_turns", 5))),
        sessions_dir=str(session_payload.get("sessions_dir", ".sessions")),
    )
    execution = ExecutionRuntimeConfig(
        max_parallel=max(1, int(execution_payload.get("max_parallel", 4))),
        fail_fast=bool(execution_payload.get("fail_fast", True)),
    )
    registration = RegistrationRuntimeConfig(
        audit_dir=str(registration_payload.get("audit_dir", "configs/audit")),
    )

    mode = str(payload.get("mode", "orchestrator_agent")).strip().lower() or "orchestrator_agent"
    if mode not in {"orchestrator_agent", "legacy_pipeline"}:
        mode = "orchestrator_agent"

    output_format = str(payload.get("output_format", "text_stream")).strip().lower() or "text_stream"
    if output_format not in {"text_stream", "json_events"}:
        output_format = "text_stream"

    return RuntimeConfig(
        schema_version=str(payload.get("schema_version", "1.0")),
        mode=mode,
        output_format=output_format,
        session=session,
        execution=execution,
        registration=registration,
    )
