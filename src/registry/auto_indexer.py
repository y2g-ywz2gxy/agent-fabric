# -*- coding: utf-8 -*-
"""基于目录扫描的 registry 自动索引同步。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from registry.discovery import build_agent_entry_payload, build_skill_entry_payload
from registry.schema import SchemaValidationError, parse_registry_entry


@dataclass(slots=True, frozen=True)
class IndexSyncResult:
    """索引同步结果。"""

    changed: bool
    changed_files: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)


class RegistryAutoIndexer:
    """扫描配置目录并维护 registry entry_files 索引。"""

    def __init__(self, config_root: Path) -> None:
        self._config_root = Path(config_root).resolve()
        self._agents_root = self._config_root / "agents"
        self._skills_root = self._config_root / "skills"
        self._agents_registry = self._agents_root / "registry.yaml"
        self._skills_registry = self._skills_root / "registry.yaml"

    def sync(self, *, force: bool = False) -> IndexSyncResult:
        """执行索引同步。"""
        _ = force
        changed_files: list[str] = []
        errors: list[str] = []

        try:
            changed_files.extend(
                self._sync_source(
                    source="agent",
                    registry_path=self._agents_registry,
                    discovered=self._scan_agents(),
                    managed_kind="python_file",
                    managed_root=self._agents_root,
                )
            )
        except Exception as exc:
            errors.append(f"agent sync failed: {exc}")

        try:
            changed_files.extend(
                self._sync_source(
                    source="skill",
                    registry_path=self._skills_registry,
                    discovered=self._scan_skills(),
                    managed_kind="skill_md",
                    managed_root=self._skills_root,
                )
            )
        except Exception as exc:
            errors.append(f"skill sync failed: {exc}")

        return IndexSyncResult(
            changed=bool(changed_files),
            changed_files=tuple(changed_files),
            errors=tuple(errors),
        )

    def _scan_agents(self) -> dict[str, dict[str, Any]]:
        discovered: dict[str, dict[str, Any]] = {}
        if not self._agents_root.exists():
            return discovered

        for py_file in sorted(self._agents_root.rglob("*.py")):
            if any(part.startswith(".") for part in py_file.parts):
                continue
            if py_file.name == "__init__.py":
                continue
            try:
                payload = build_agent_entry_payload(py_file)
            except Exception:
                continue
            discovered[str(payload["id"])] = payload
        return discovered

    def _scan_skills(self) -> dict[str, dict[str, Any]]:
        discovered: dict[str, dict[str, Any]] = {}
        if not self._skills_root.exists():
            return discovered

        for skill_md in sorted(self._skills_root.rglob("SKILL.md")):
            if any(part.startswith(".") for part in skill_md.parts):
                continue
            try:
                payload = build_skill_entry_payload(skill_md)
            except Exception:
                continue
            discovered[str(payload["id"])] = payload
        return discovered

    def _sync_source(
        self,
        *,
        source: str,
        registry_path: Path,
        discovered: dict[str, dict[str, Any]],
        managed_kind: str,
        managed_root: Path,
    ) -> list[str]:
        changed: list[str] = []
        payload = self._read_registry_payload(registry_path)
        payload.setdefault("schema_version", "1.0")

        if "entry_files" not in payload:
            migrated = self._migrate_inline_entries(
                source=source,
                registry_path=registry_path,
                raw_entries=payload.get("entries", []),
            )
            changed.extend(migrated["changed_files"])
            payload["entry_files"] = migrated["entry_files"]
            payload.pop("entries", None)
            changed.append(str(registry_path))

        raw_entry_files = payload.get("entry_files", [])
        if not isinstance(raw_entry_files, list):
            raise SchemaValidationError(f"{registry_path}: entry_files must be a list")
        entry_files = [str(item) for item in raw_entry_files]

        existing_entries: dict[str, dict[str, Any]] = {}
        existing_rel_by_id: dict[str, str] = {}
        managed_existing_ids: set[str] = set()
        for rel in list(entry_files):
            abs_path = (registry_path.parent / rel).resolve()
            if not abs_path.exists():
                continue
            entry_doc = self._read_yaml(abs_path)
            entry_raw = entry_doc.get("entry") if "entry" in entry_doc else entry_doc
            parsed = parse_registry_entry(entry_raw, source=source, source_path=str(abs_path))
            current = {
                "id": parsed.id,
                "description": parsed.description,
                "capabilities": list(parsed.capabilities),
                "entrypoint": parsed.entrypoint,
                "loader_kind": parsed.loader_kind,
                "loader_target": parsed.loader_target,
                "dependencies": list(parsed.dependencies),
                "healthcheck": parsed.healthcheck,
                "version": parsed.version,
                "origin": parsed.origin,
            }
            existing_entries[parsed.id] = current
            existing_rel_by_id[parsed.id] = rel
            if self._is_managed_entry(current, expected_kind=managed_kind, root=managed_root):
                managed_existing_ids.add(parsed.id)

        desired_ids = set(discovered.keys())
        for entry_id, doc in sorted(discovered.items()):
            rel = existing_rel_by_id.get(entry_id) or str(Path("entries") / f"{entry_id}.yaml").replace("\\", "/")
            abs_path = (registry_path.parent / rel).resolve()
            abs_path.parent.mkdir(parents=True, exist_ok=True)

            current = existing_entries.get(entry_id)
            if current != doc:
                abs_path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
                changed.append(str(abs_path))

            if rel not in entry_files:
                entry_files.append(rel)
                changed.append(str(registry_path))

        stale_ids = managed_existing_ids - desired_ids
        for entry_id in sorted(stale_ids):
            rel = existing_rel_by_id.get(entry_id)
            if not rel:
                continue
            abs_path = (registry_path.parent / rel).resolve()
            if abs_path.exists():
                abs_path.unlink(missing_ok=True)
                changed.append(str(abs_path))
            if rel in entry_files:
                entry_files.remove(rel)
                changed.append(str(registry_path))

        unique_entry_files = sorted({item for item in entry_files})
        if payload.get("entry_files") != unique_entry_files:
            payload["entry_files"] = unique_entry_files
            changed.append(str(registry_path))

        if str(registry_path) in changed:
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

        return sorted(set(changed))

    @staticmethod
    def _is_managed_entry(entry: Mapping[str, Any], *, expected_kind: str, root: Path) -> bool:
        if str(entry.get("loader_kind", "")) != expected_kind:
            return False
        target = str(entry.get("loader_target", "")).strip()
        if not target:
            return False
        if expected_kind == "python_file":
            target = target.split(":", 1)[0]
        target_path = Path(target).resolve()
        try:
            target_path.relative_to(root.resolve())
        except ValueError:
            return False
        return True

    def _read_registry_payload(self, registry_path: Path) -> dict[str, Any]:
        if not registry_path.exists():
            return {"schema_version": "1.0", "entry_files": []}
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if payload is None:
            return {"schema_version": "1.0", "entry_files": []}
        if not isinstance(payload, Mapping):
            raise SchemaValidationError(f"{registry_path}: YAML root must be mapping")
        return dict(payload)

    def _migrate_inline_entries(
        self,
        *,
        source: str,
        registry_path: Path,
        raw_entries: Any,
    ) -> dict[str, Any]:
        changed_files: list[str] = []
        entry_files: list[str] = []
        if not isinstance(raw_entries, list):
            raw_entries = []
        for index, raw_entry in enumerate(raw_entries):
            parsed = parse_registry_entry(
                raw_entry,
                source=source,
                source_path=f"{registry_path}:entries[{index}]",
            )
            rel = str(Path("entries") / f"{parsed.id}.yaml").replace("\\", "/")
            abs_path = (registry_path.parent / rel).resolve()
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(
                yaml.safe_dump(
                    {
                        "id": parsed.id,
                        "description": parsed.description,
                        "capabilities": list(parsed.capabilities),
                        "entrypoint": parsed.entrypoint,
                        "loader_kind": parsed.loader_kind,
                        "loader_target": parsed.loader_target,
                        "dependencies": list(parsed.dependencies),
                        "healthcheck": parsed.healthcheck,
                        "version": parsed.version,
                        "origin": parsed.origin,
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            changed_files.append(str(abs_path))
            entry_files.append(rel)
        return {"changed_files": changed_files, "entry_files": sorted(set(entry_files))}

    @staticmethod
    def _read_yaml(path: Path) -> Mapping[str, Any]:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload is None:
            return {}
        if not isinstance(payload, Mapping):
            raise SchemaValidationError(f"{path}: YAML root must be mapping")
        return payload
