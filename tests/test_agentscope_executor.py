from __future__ import annotations

from orchestrator.agentscope_executor import AgentScopeReActExecutor, AgentScopeRuntimeConfig
from orchestrator.result import ExecutionResult


class _FallbackExecutor:
    def execute(self, query: str, plan_data):
        return ExecutionResult.success(
            {
                "answer": f"fallback:{query}",
                "plan": dict(plan_data),
                "executor": "rule-based",
            },
            next_action="completed",
        )


def test_agentscope_executor_falls_back_when_disabled() -> None:
    executor = AgentScopeReActExecutor(
        fallback_executor=_FallbackExecutor(),
        runtime_config=AgentScopeRuntimeConfig(
            enabled=False,
            provider="openai",
            model_name="gpt-4o-mini",
            api_key=None,
        ),
    )

    result = executor.execute("hello", {"steps": []})

    assert result.ok
    assert result.data["executor"] == "rule-based"
    assert result.data["degraded"] is True
    assert result.data["degrade_reason"] == "agentscope_not_enabled_or_missing_credentials"


def test_agentscope_executor_requires_credentials_for_openai_provider() -> None:
    config = AgentScopeRuntimeConfig(
        enabled=True,
        provider="openai",
        model_name="gpt-4o-mini",
        api_key=None,
    )
    assert not config.is_usable()

