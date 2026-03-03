from __future__ import annotations

import textwrap
from pathlib import Path

from orchestrator.agentscope_executor import AgentScopeReActExecutor, AgentScopeRuntimeConfig


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_executor_invokes_python_file_entrypoint(tmp_path: Path) -> None:
    agent_file = tmp_path / "agent_file.py"
    _write(
        agent_file,
        """
        def run(payload):
            return {"task": payload["task"], "ok": True}
        """,
    )

    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        )
    )
    executor._candidate_index = {
        "py-file-agent": {
            "id": "py-file-agent",
            "source": "agent",
            "entrypoint": f"{agent_file}:run",
            "loader_kind": "python_file",
            "loader_target": f"{agent_file}:run",
            "capabilities": ["qa.check"],
            "version": "0.1.0",
        }
    }

    result = executor._invoke_registry_entry("py-file-agent", "validate", {"x": 1})
    assert result["entry_id"] == "py-file-agent"
    assert result["result"]["ok"] is True
    assert result["result"]["task"] == "validate"


def test_executor_invokes_skill_md_with_adapter(monkeypatch, tmp_path: Path) -> None:
    skill_md = tmp_path / "demo-skill" / "SKILL.md"
    _write(
        skill_md,
        """
        ---
        name: demo-skill
        description: Demo
        ---
        # Demo Skill
        """,
    )

    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        )
    )
    executor._candidate_index = {
        "demo-skill": {
            "id": "demo-skill",
            "source": "skill",
            "entrypoint": str(skill_md),
            "loader_kind": "skill_md",
            "loader_target": str(skill_md),
            "capabilities": ["demo.cap"],
            "version": "0.1.0",
        }
    }

    monkeypatch.setattr(
        type(executor._skill_md_adapter),
        "execute",
        lambda self, **kwargs: {"answer": f"ok:{kwargs['task']}"},
    )

    result = executor._invoke_registry_entry("demo-skill", "compose", {"k": "v"})
    assert result["entry_id"] == "demo-skill"
    assert result["result"]["answer"] == "ok:compose"
