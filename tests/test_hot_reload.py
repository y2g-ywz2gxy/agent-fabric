from __future__ import annotations

from pathlib import Path

from registry.hot_reload import RegistryHotReloader
from registry.transaction import RegistryTransactionManager


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    agents = tmp_path / "agents.yaml"
    skills = tmp_path / "skills.yaml"

    _write(
        agents,
        """
schema_version: "1.0"
entries:
  - id: a1
    capabilities: [finance.analysis]
    entrypoint: agents.a1:run
    dependencies: []
    healthcheck: ok
    version: "0.1.0"
""".strip(),
    )
    _write(
        skills,
        """
schema_version: "1.0"
entries:
  - id: s1
    capabilities: [general.assistant]
    entrypoint: skills.s1:run
    dependencies: []
    healthcheck: ok
    version: "0.1.0"
""".strip(),
    )
    return agents, skills


def test_hot_reload_applies_valid_new_entry(tmp_path: Path) -> None:
    agents, skills = _bootstrap(tmp_path)
    manager = RegistryTransactionManager(agents, skills)
    reloader = RegistryHotReloader(manager)

    _write(
        agents,
        """
schema_version: "1.0"
entries:
  - id: a1
    capabilities: [finance.analysis]
    entrypoint: agents.a1:run
    dependencies: []
    healthcheck: ok
    version: "0.1.0"
  - id: a2
    capabilities: [support.troubleshoot]
    entrypoint: agents.a2:run
    dependencies: []
    healthcheck: ok
    version: "0.1.0"
""".strip(),
    )

    event = reloader.scan_and_reload(force=True)

    assert event.changed
    assert event.applied
    assert not event.rolled_back
    snapshot = manager.get_snapshot()
    assert any("support.troubleshoot" in item.capabilities for item in snapshot.agents)


def test_hot_reload_rolls_back_on_invalid_config(tmp_path: Path) -> None:
    agents, skills = _bootstrap(tmp_path)
    manager = RegistryTransactionManager(agents, skills)
    reloader = RegistryHotReloader(manager)

    _write(
        agents,
        """
schema_version: "1.0"
entries:
  - id: broken
    capabilities: [finance.analysis]
    entrypoint: agents.broken:run
    dependencies: []
    version: "0.1.0"
""".strip(),
    )

    event = reloader.scan_and_reload(force=True)

    assert event.changed
    assert not event.applied
    assert event.rolled_back
    snapshot = manager.get_snapshot()
    assert len(snapshot.agents) == 1
    assert snapshot.agents[0].id == "a1"
