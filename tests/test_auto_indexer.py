from __future__ import annotations

import textwrap
from pathlib import Path

from registry.auto_indexer import RegistryAutoIndexer
from registry.config_loader import load_registry_snapshot


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_auto_indexer_scans_and_reconciles(tmp_path: Path) -> None:
    config_root = tmp_path / "configs"
    _write(
        config_root / "agents" / "registry.yaml",
        """
        schema_version: "1.0"
        entry_files: []
        """,
    )
    _write(
        config_root / "skills" / "registry.yaml",
        """
        schema_version: "1.0"
        entry_files: []
        """,
    )
    _write(
        config_root / "agents" / "qa_agent.py",
        """
        AGENT_META = {
            "id": "qa-agent",
            "description": "Quality checker",
            "capabilities": ["qa.check"],
            "version": "0.2.0",
        }

        def run(payload):
            return {"ok": True, "task": payload.get("task")}
        """,
    )
    _write(
        config_root / "skills" / "writer-skill" / "SKILL.md",
        """
        ---
        name: writer-skill
        description: Help writing drafts
        metadata:
          capabilities:
            - writing.draft
          version: "0.1.0"
        ---

        # Writer Skill
        """,
    )

    indexer = RegistryAutoIndexer(config_root)
    result = indexer.sync(force=True)
    assert result.changed
    assert not result.errors

    snapshot = load_registry_snapshot(
        config_root / "agents" / "registry.yaml",
        config_root / "skills" / "registry.yaml",
    )
    assert any(entry.id == "qa-agent" and entry.loader_kind == "python_file" for entry in snapshot.agents)
    assert any(entry.id == "writer-skill" and entry.loader_kind == "skill_md" for entry in snapshot.skills)

    (config_root / "skills" / "writer-skill" / "SKILL.md").unlink()
    result2 = indexer.sync(force=True)
    assert result2.changed

    snapshot2 = load_registry_snapshot(
        config_root / "agents" / "registry.yaml",
        config_root / "skills" / "registry.yaml",
    )
    assert all(entry.id != "writer-skill" for entry in snapshot2.skills)
