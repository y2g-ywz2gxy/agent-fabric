from __future__ import annotations

import textwrap
from pathlib import Path

from orchestrator.agentscope_executor import AgentScopeReActExecutor, AgentScopeRuntimeConfig
from registry.builtin_provider import BuiltinRegistryProvider
from registry.schema import RegistryEntry, RegistrySnapshot


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


class _FakeChatAgent:
    def __init__(self) -> None:
        self.stream_enabled = True

    def set_console_output_enabled(self, enabled: bool) -> None:
        self.stream_enabled = enabled

    async def __call__(self, msg):
        from agentscope.message import Msg

        return Msg(name="assistant", role="assistant", content=f"reply:{msg.content}")


def test_builtin_provider_includes_advisor_agents() -> None:
    provider = BuiltinRegistryProvider(project_root=Path.cwd())
    entries = provider.builtin_entries()
    ids = {entry.id for entry in entries}

    assert "route-advisor-agent" in ids
    assert "planner-advisor-agent" in ids
    assert "healing-advisor-agent" in ids


def test_executor_can_refresh_integrations_and_chat(monkeypatch, tmp_path: Path) -> None:
    skill_md = tmp_path / "skill-demo" / "SKILL.md"
    _write(
        skill_md,
        """
        ---
        name: demo-skill
        description: demo skill
        ---

        # Demo
        """,
    )

    snapshot = RegistrySnapshot(
        schema_version="1.0",
        agents=(
            RegistryEntry(
                id="demo-agent",
                description="demo",
                capabilities=("demo.cap",),
                entrypoint="demo.module:run",
                dependencies=(),
                healthcheck="ok",
                version="0.1.0",
                source="agent",
                origin="dynamic",
                loader_kind="python_module",
                loader_target="demo.module:run",
            ),
        ),
        skills=(
            RegistryEntry(
                id="demo-skill",
                description="demo skill",
                capabilities=("demo.skill",),
                entrypoint=str(skill_md),
                dependencies=(),
                healthcheck="skill-md:demo",
                version="0.1.0",
                source="skill",
                origin="dynamic",
                loader_kind="skill_md",
                loader_target=str(skill_md),
            ),
        ),
    )

    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        )
    )

    monkeypatch.setattr("orchestrator.agentscope_runtime.AgentScopeFactory.ensure_usable", lambda self: None)
    monkeypatch.setattr(executor, "_ensure_agent", lambda: _FakeChatAgent())

    refresh = executor.refresh_integrations(snapshot)
    assert refresh["entries"] == 2
    assert refresh["callable_tools"] >= 3

    result = executor.chat("hello", stream=False)
    assert result.ok
    assert "reply:hello" in str(result.data.get("answer", ""))
