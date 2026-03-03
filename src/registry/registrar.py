# -*- coding: utf-8 -*-
"""注册表本地动态注册能力。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from registry.discovery import entry_to_payload
from registry.schema import RegistryEntry, SchemaValidationError, parse_registry_entry
from registry.transaction import RegistryTransactionManager


@dataclass(slots=True, frozen=True)
class RegistrationResult:
    """注册执行结果。"""

    success: bool
    source: str
    entry_id: str | None
    message: str
    audit_path: str | None = None
    changed_files: tuple[str, ...] = field(default_factory=tuple)


class RegistryRegistrar:
    """基于配置文件的本地注册器。"""

    def __init__(self, manager: RegistryTransactionManager, *, audit_dir: Path) -> None:
        self._manager = manager
        self._audit_dir = audit_dir

    def register(
        self,
        *,
        source: str,
        entry: Mapping[str, Any],
        actor: str,
        session_id: str,
    ) -> RegistrationResult:
        """注册 agent/skill。"""
        source = source.strip().lower()
        if source not in {"agent", "skill"}:
            return self._failed(
                source=source,
                entry_id=str(entry.get("id") or ""),
                actor=actor,
                session_id=session_id,
                message=f"unsupported source: {source}",
            )

        normalized = self._normalize_entry(entry, source=source)
        if isinstance(normalized, str):
            return self._failed(
                source=source,
                entry_id=str(entry.get("id") or ""),
                actor=actor,
                session_id=session_id,
                message=normalized,
            )

        entry_id = normalized["id"]
        snapshot = self._manager.get_snapshot()
        if any(item.id == entry_id for item in snapshot.all_entries):
            return self._failed(
                source=source,
                entry_id=entry_id,
                actor=actor,
                session_id=session_id,
                message=f"duplicate entry id: {entry_id}",
            )

        registry_path = self._registry_path(source)
        original_registry_text = registry_path.read_text(encoding="utf-8") if registry_path.exists() else ""
        changed_files: list[str] = []
        created_entry_file: Path | None = None

        try:
            registry_payload = self._read_yaml_or_empty(registry_path)
            changed_files.extend(self._ensure_entry_file_index_layout(source=source, registry_path=registry_path, payload=registry_payload))

            registry_payload.setdefault("schema_version", "1.0")
            raw_entry_files = registry_payload.setdefault("entry_files", [])
            if not isinstance(raw_entry_files, list):
                raise SchemaValidationError(f"{registry_path}: entry_files must be a list")

            entry_rel = str(Path("entries") / f"{entry_id}.yaml").replace("\\", "/")
            if entry_rel in raw_entry_files:
                raise SchemaValidationError(f"{registry_path}: duplicate entry file index for {entry_rel}")

            entry_abs = (registry_path.parent / entry_rel).resolve()
            try:
                entry_abs.relative_to(registry_path.parent.resolve())
            except ValueError as exc:
                raise SchemaValidationError("entry path escapes registry directory") from exc
            if entry_abs.exists():
                raise SchemaValidationError(f"entry file already exists: {entry_abs}")

            entry_abs.parent.mkdir(parents=True, exist_ok=True)
            entry_abs.write_text(
                yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            created_entry_file = entry_abs
            changed_files.append(str(entry_abs))

            raw_entry_files.append(entry_rel)
            registry_payload["entry_files"] = sorted({str(item) for item in raw_entry_files})
            registry_payload.pop("entries", None)
            registry_path.write_text(
                yaml.safe_dump(registry_payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            changed_files.append(str(registry_path))

            reload_result = self._manager.reload()
            if not reload_result.success:
                raise RuntimeError(reload_result.error or "reload failed")

            audit_path = self._write_audit(
                action="register",
                status="success",
                actor=actor,
                session_id=session_id,
                source=source,
                entry_id=entry_id,
                message="registration applied",
                changed_files=changed_files,
            )
            return RegistrationResult(
                success=True,
                source=source,
                entry_id=entry_id,
                message="registration applied",
                audit_path=str(audit_path),
                changed_files=tuple(changed_files),
            )
        except Exception as exc:
            if created_entry_file and created_entry_file.exists():
                created_entry_file.unlink(missing_ok=True)
            registry_path.write_text(original_registry_text, encoding="utf-8")
            # 恢复内存快照到文件回滚后的状态
            self._manager.reload()
            return self._failed(
                source=source,
                entry_id=entry_id,
                actor=actor,
                session_id=session_id,
                message=str(exc),
                changed_files=changed_files,
            )

    def audit_denied(
        self,
        *,
        source: str,
        actor: str,
        session_id: str,
        message: str,
        entry_id: str | None = None,
    ) -> RegistrationResult:
        """记录拒绝类审计。"""
        audit_path = self._write_audit(
            action="register",
            status="denied",
            actor=actor,
            session_id=session_id,
            source=source,
            entry_id=entry_id,
            message=message,
            changed_files=[],
        )
        return RegistrationResult(
            success=False,
            source=source,
            entry_id=entry_id,
            message=message,
            audit_path=str(audit_path),
            changed_files=tuple(),
        )

    def audit_failed(
        self,
        *,
        source: str,
        actor: str,
        session_id: str,
        message: str,
        entry_id: str | None = None,
    ) -> RegistrationResult:
        """记录失败类审计（非权限拒绝）。"""
        audit_path = self._write_audit(
            action="register",
            status="failed",
            actor=actor,
            session_id=session_id,
            source=source,
            entry_id=entry_id,
            message=message,
            changed_files=[],
        )
        return RegistrationResult(
            success=False,
            source=source,
            entry_id=entry_id,
            message=message,
            audit_path=str(audit_path),
            changed_files=tuple(),
        )

    def _failed(
        self,
        *,
        source: str,
        entry_id: str,
        actor: str,
        session_id: str,
        message: str,
        changed_files: list[str] | None = None,
    ) -> RegistrationResult:
        audit_path = self._write_audit(
            action="register",
            status="failed",
            actor=actor,
            session_id=session_id,
            source=source,
            entry_id=entry_id,
            message=message,
            changed_files=changed_files or [],
        )
        return RegistrationResult(
            success=False,
            source=source,
            entry_id=entry_id or None,
            message=message,
            audit_path=str(audit_path),
            changed_files=tuple(changed_files or []),
        )

    def _normalize_entry(self, entry: Mapping[str, Any], *, source: str) -> dict[str, Any] | str:
        try:
            parsed = parse_registry_entry(entry, source=source, source_path=f"register.{source}")
        except Exception as exc:
            return str(exc)
        return self._entry_to_payload(parsed)

    def _ensure_entry_file_index_layout(
        self,
        *,
        source: str,
        registry_path: Path,
        payload: dict[str, Any],
    ) -> list[str]:
        changed_files: list[str] = []
        if "entry_files" in payload:
            return changed_files

        raw_entries = payload.get("entries", [])
        if not isinstance(raw_entries, list):
            raise SchemaValidationError(f"{registry_path}: entries must be a list")

        payload.setdefault("schema_version", "1.0")
        payload["entry_files"] = []

        entries_dir = registry_path.parent / "entries"
        entries_dir.mkdir(parents=True, exist_ok=True)

        for index, raw_entry in enumerate(raw_entries):
            parsed = parse_registry_entry(
                raw_entry,
                source=source,
                source_path=f"{registry_path}:entries[{index}]",
            )
            entry_payload = self._entry_to_payload(parsed)
            entry_rel = str(Path("entries") / f"{parsed.id}.yaml").replace("\\", "/")
            entry_abs = (registry_path.parent / entry_rel).resolve()
            if not entry_abs.exists():
                entry_abs.write_text(
                    yaml.safe_dump(entry_payload, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                changed_files.append(str(entry_abs))
            payload["entry_files"].append(entry_rel)

        payload["entry_files"] = sorted({str(item) for item in payload["entry_files"]})
        payload.pop("entries", None)
        return changed_files

    def _registry_path(self, source: str) -> Path:
        if source == "agent":
            return self._manager.agents_registry_path
        return self._manager.skills_registry_path

    @staticmethod
    def _read_yaml_or_empty(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload is None:
            return {}
        if not isinstance(payload, Mapping):
            raise SchemaValidationError(f"{path}: YAML root must be a mapping")
        return dict(payload)

    def _write_audit(
        self,
        *,
        action: str,
        status: str,
        actor: str,
        session_id: str,
        source: str,
        entry_id: str | None,
        message: str,
        changed_files: list[str],
    ) -> Path:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
        safe_source = source or "unknown"
        safe_id = (entry_id or "unknown").replace("/", "_")
        file_path = self._audit_dir / f"{timestamp}_{safe_source}_{safe_id}_{status}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "timestamp": now.isoformat(),
            "action": action,
            "status": status,
            "actor": actor,
            "session_id": session_id,
            "source": source,
            "entry_id": entry_id,
            "message": message,
            "changed_files": list(changed_files),
        }
        file_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return file_path

    @staticmethod
    def _entry_to_payload(entry: RegistryEntry) -> dict[str, Any]:
        return entry_to_payload(entry)
