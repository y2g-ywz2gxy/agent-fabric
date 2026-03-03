from __future__ import annotations

import textwrap
from pathlib import Path

from registry.registrar import RegistryRegistrar
from registry.transaction import RegistryTransactionManager


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    agents = tmp_path / "agents" / "registry.yaml"
    skills = tmp_path / "skills" / "registry.yaml"

    _write(
        agents,
        """
        schema_version: "1.0"
        entries:
          - id: a1
            capabilities: [cap.agent]
            entrypoint: agents.a1:run
            dependencies: []
            healthcheck: ok
            version: "0.1.0"
        """,
    )
    _write(
        skills,
        """
        schema_version: "1.0"
        entries:
          - id: s1
            capabilities: [cap.skill]
            entrypoint: skills.s1:run
            dependencies: []
            healthcheck: ok
            version: "0.1.0"
        """,
    )
    return agents, skills


def test_registrar_registers_entry_and_writes_audit(tmp_path: Path) -> None:
    agents, skills = _bootstrap(tmp_path)
    manager = RegistryTransactionManager(agents, skills)
    registrar = RegistryRegistrar(manager, audit_dir=tmp_path / "audit")

    result = registrar.register(
        source="skill",
        entry={
            "id": "s2",
            "capabilities": ["cap.new"],
            "entrypoint": "skills.s2:run",
            "dependencies": [],
            "healthcheck": "ok",
            "version": "0.1.0",
        },
        actor="admin",
        session_id="sess-1",
    )

    assert result.success
    assert result.entry_id == "s2"
    assert result.audit_path is not None
    assert Path(result.audit_path).exists()

    snapshot = manager.get_snapshot()
    assert any(entry.id == "s2" for entry in snapshot.skills)

    # 旧格式会自动迁移为 entry_files 索引
    skills_doc = skills.read_text(encoding="utf-8")
    assert "entry_files" in skills_doc
    assert "entries:" not in skills_doc
    assert (skills.parent / "entries" / "s2.yaml").exists()


def test_registrar_rejects_duplicate_id_globally(tmp_path: Path) -> None:
    agents, skills = _bootstrap(tmp_path)
    manager = RegistryTransactionManager(agents, skills)
    registrar = RegistryRegistrar(manager, audit_dir=tmp_path / "audit")

    result = registrar.register(
        source="skill",
        entry={
            "id": "a1",
            "capabilities": ["cap.new"],
            "entrypoint": "skills.s2:run",
            "dependencies": [],
            "healthcheck": "ok",
            "version": "0.1.0",
        },
        actor="admin",
        session_id="sess-1",
    )

    assert not result.success
    assert "duplicate entry id" in result.message
    assert result.audit_path is not None


def test_registrar_can_record_denied_event(tmp_path: Path) -> None:
    agents, skills = _bootstrap(tmp_path)
    manager = RegistryTransactionManager(agents, skills)
    registrar = RegistryRegistrar(manager, audit_dir=tmp_path / "audit")

    denied = registrar.audit_denied(
        source="skill",
        actor="user",
        session_id="sess-2",
        message="permission denied",
    )

    assert not denied.success
    assert denied.audit_path is not None
    assert Path(denied.audit_path).exists()
