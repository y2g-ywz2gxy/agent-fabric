from __future__ import annotations

import types

from agentscope.message import Msg

from orchestrator.agentscope_executor import AgentScopeReActExecutor, AgentScopeRuntimeConfig
from orchestrator.result import ExecutionStatus


class _FakeAgent:
    async def __call__(self, msg):
        return Msg(name="assistant", role="assistant", content=f"done:{msg.content}")


def test_agentscope_executor_fails_when_disabled() -> None:
    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=False,
            provider="openai",
            model_name="gpt-4o-mini",
            api_key=None,
        ),
    )

    result = executor.execute("hello", {"steps": []})

    assert result.status is ExecutionStatus.FAILED
    assert "not usable" in (result.error or "")


def test_agentscope_executor_requires_credentials_for_openai_provider() -> None:
    config = AgentScopeRuntimeConfig(
        enabled=True,
        provider="openai",
        model_name="gpt-4o-mini",
        api_key=None,
    )
    assert not config.is_usable()


def test_agentscope_executor_works_with_mocked_agent(monkeypatch) -> None:
    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        ),
    )
    monkeypatch.setattr(executor, "_ensure_agent", lambda: _FakeAgent())

    result = executor.execute("ship it", {"steps": [{"id": "step-01", "action": "run"}]})

    assert result.ok
    assert result.data["executor"] == "agentscope-react"
    assert "ship it" in result.data["answer"]


def test_invoke_registry_entry_calls_python_entrypoint(monkeypatch) -> None:
    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        ),
    )
    executor._candidate_index = {
        "demo": {
            "id": "demo",
            "entrypoint": "demo_module:run",
            "source": "skill",
            "capabilities": ["demo.cap"],
            "version": "0.1.0",
        }
    }

    module = types.ModuleType("demo_module")

    def run(payload):
        return {"ok": True, "task": payload["task"]}

    module.run = run
    monkeypatch.setattr("importlib.import_module", lambda name: module)

    result = executor._invoke_registry_entry("demo", "do something", {"x": 1})

    assert result["entry_id"] == "demo"
    assert result["result"]["ok"] is True
