from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from registry.config_loader import load_registry_snapshot
from registry.schema import SchemaValidationError


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_load_registry_snapshot_supports_entry_files(tmp_path: Path) -> None:
    agents_registry = tmp_path / "agents" / "registry.yaml"
    skills_registry = tmp_path / "skills" / "registry.yaml"

    _write(
        agents_registry,
        """
        schema_version: "1.0"
        entry_files:
          - entries/a1.yaml
        """,
    )
    _write(
        agents_registry.parent / "entries" / "a1.yaml",
        """
        id: a1
        capabilities: [cap.a]
        entrypoint: agents.a1:run
        dependencies: []
        healthcheck: ok
        version: "0.1.0"
        """,
    )

    _write(
        skills_registry,
        """
        schema_version: "1.0"
        entry_files:
          - entries/s1.yaml
        """,
    )
    _write(
        skills_registry.parent / "entries" / "s1.yaml",
        """
        id: s1
        capabilities: [cap.s]
        entrypoint: skills.s1:run
        dependencies: []
        healthcheck: ok
        version: "0.1.0"
        """,
    )

    snapshot = load_registry_snapshot(agents_registry, skills_registry)

    assert snapshot.schema_version == "1.0"
    assert snapshot.agents[0].id == "a1"
    assert snapshot.skills[0].id == "s1"


def test_load_registry_snapshot_rejects_global_duplicate_ids(tmp_path: Path) -> None:
    agents_registry = tmp_path / "agents" / "registry.yaml"
    skills_registry = tmp_path / "skills" / "registry.yaml"

    _write(
        agents_registry,
        """
        schema_version: "1.0"
        entries:
          - id: duplicated
            capabilities: [cap.a]
            entrypoint: agents.a:run
            dependencies: []
            healthcheck: ok
            version: "0.1.0"
        """,
    )
    _write(
        skills_registry,
        """
        schema_version: "1.0"
        entries:
          - id: duplicated
            capabilities: [cap.s]
            entrypoint: skills.s:run
            dependencies: []
            healthcheck: ok
            version: "0.1.0"
        """,
    )

    with pytest.raises(SchemaValidationError, match="global: duplicate entry id"):
        load_registry_snapshot(agents_registry, skills_registry)
