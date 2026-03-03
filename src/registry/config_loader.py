from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from registry.schema import RegistrySnapshot, SchemaValidationError, parse_registry_payload


def load_registry_snapshot(
    agents_registry_path: str | Path,
    skills_registry_path: str | Path,
) -> RegistrySnapshot:
    agents_path = Path(agents_registry_path)
    skills_path = Path(skills_registry_path)

    agents_payload = _read_yaml(agents_path)
    skills_payload = _read_yaml(skills_path)

    agents_version, agents = parse_registry_payload(
        agents_payload,
        source="agent",
        source_path=str(agents_path),
    )
    skills_version, skills = parse_registry_payload(
        skills_payload,
        source="skill",
        source_path=str(skills_path),
    )

    if agents_version != skills_version:
        raise SchemaValidationError(
            f"schema_version mismatch: agents={agents_version}, skills={skills_version}"
        )

    return RegistrySnapshot(schema_version=agents_version, agents=agents, skills=skills)


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing registry file: {path}")

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise SchemaValidationError(f"{path}: YAML root must be a mapping")
    return payload
