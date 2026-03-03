from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


class SchemaValidationError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class RegistryEntry:
    id: str
    capabilities: tuple[str, ...]
    entrypoint: str
    dependencies: tuple[str, ...]
    healthcheck: str
    version: str
    source: str


@dataclass(slots=True, frozen=True)
class RegistrySnapshot:
    schema_version: str
    agents: tuple[RegistryEntry, ...]
    skills: tuple[RegistryEntry, ...]
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def all_entries(self) -> tuple[RegistryEntry, ...]:
        return self.agents + self.skills

    def find_by_capabilities(self, capabilities: list[str] | tuple[str, ...]) -> tuple[RegistryEntry, ...]:
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
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(f"{source_path}: payload must be a mapping")

    schema_version = payload.get("schema_version")
    if not schema_version:
        raise SchemaValidationError(f"{source_path}: schema_version is required")

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise SchemaValidationError(f"{source_path}: entries must be a list")

    entries: list[RegistryEntry] = []
    for index, raw in enumerate(raw_entries):
        entry_path = f"{source_path}:entries[{index}]"
        entries.append(_parse_entry(raw, source=source, source_path=entry_path))

    return str(schema_version), tuple(entries)


def _parse_entry(raw: Any, *, source: str, source_path: str) -> RegistryEntry:
    if not isinstance(raw, Mapping):
        raise SchemaValidationError(f"{source_path}: entry must be a mapping")

    required = ("id", "capabilities", "entrypoint", "dependencies", "healthcheck", "version")
    missing = [key for key in required if key not in raw]
    if missing:
        raise SchemaValidationError(f"{source_path}: missing required fields: {', '.join(missing)}")

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

    return RegistryEntry(
        id=str(raw["id"]),
        capabilities=tuple(str(capability) for capability in capabilities),
        entrypoint=str(raw["entrypoint"]),
        dependencies=tuple(str(dependency) for dependency in dependencies),
        healthcheck=str(raw["healthcheck"]),
        version=str(raw["version"]),
        source=source,
    )
