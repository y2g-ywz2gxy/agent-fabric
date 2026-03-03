from __future__ import annotations

import threading
from pathlib import Path

from registry.transaction import RegistryTransactionManager


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _valid_agents(count: int) -> str:
    entries = []
    for idx in range(1, count + 1):
        entries.append(
            f"""
  - id: a{idx}
    capabilities: [cap.{idx}]
    entrypoint: agents.a{idx}:run
    dependencies: []
    healthcheck: ok
    version: "0.1.0"
""".rstrip()
        )
    return "schema_version: \"1.0\"\nentries:\n" + "\n".join(entries)


def _skills() -> str:
    return """
schema_version: "1.0"
entries:
  - id: s1
    capabilities: [general.assistant]
    entrypoint: skills.s1:run
    dependencies: []
    healthcheck: ok
    version: "0.1.0"
""".strip()


def test_registry_atomic_swap_never_exposes_partial_state(tmp_path: Path) -> None:
    agents = tmp_path / "agents.yaml"
    skills = tmp_path / "skills.yaml"
    _write(agents, _valid_agents(1))
    _write(skills, _skills())

    manager = RegistryTransactionManager(agents, skills)
    stop = threading.Event()
    observed_agent_counts: list[int] = []
    observed_health_ok: list[bool] = []

    def reader() -> None:
        while not stop.is_set():
            snapshot = manager.get_snapshot()
            observed_agent_counts.append(len(snapshot.agents))
            observed_health_ok.append(all(bool(item.healthcheck) for item in snapshot.all_entries))

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()

    _write(agents, _valid_agents(3))
    result = manager.reload()

    stop.set()
    for thread in threads:
        thread.join()

    assert result.success
    assert set(observed_agent_counts).issubset({1, 3})
    assert all(observed_health_ok)


def test_registry_bad_reload_rolls_back_without_partial_state(tmp_path: Path) -> None:
    agents = tmp_path / "agents.yaml"
    skills = tmp_path / "skills.yaml"
    _write(agents, _valid_agents(1))
    _write(skills, _skills())

    manager = RegistryTransactionManager(agents, skills)
    stop = threading.Event()
    observed_agent_counts: list[int] = []

    def reader() -> None:
        while not stop.is_set():
            snapshot = manager.get_snapshot()
            observed_agent_counts.append(len(snapshot.agents))

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()

    _write(
        agents,
        """
schema_version: "1.0"
entries:
  - id: broken
    capabilities: [cap.bad]
    entrypoint: agents.broken:run
    dependencies: []
    version: "0.1.0"
""".strip(),
    )
    result = manager.reload()

    stop.set()
    for thread in threads:
        thread.join()

    assert not result.success
    assert result.rolled_back
    assert set(observed_agent_counts).issubset({1})
