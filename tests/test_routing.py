from __future__ import annotations

from config.model_config import ModelConfig
from orchestrator.router import AgentScopeRouter, RouteDecision
from registry.schema import RegistryEntry, RegistrySnapshot


def _snapshot() -> RegistrySnapshot:
    return RegistrySnapshot(
        schema_version="1.0",
        agents=(
            RegistryEntry(
                id="finance-router-agent",
                capabilities=("finance.analysis", "planning.decompose"),
                entrypoint="agents.finance:run",
                dependencies=("http-rag",),
                healthcheck="ok",
                version="0.1.0",
                source="agent",
            ),
            RegistryEntry(
                id="support-triage-agent",
                capabilities=("support.troubleshoot", "healing.resolve"),
                entrypoint="agents.support:run",
                dependencies=("toolkit",),
                healthcheck="ok",
                version="0.1.0",
                source="agent",
            ),
        ),
        skills=(
            RegistryEntry(
                id="market-rag-skill",
                capabilities=("research.rag", "planning.decompose"),
                entrypoint="skills.research:run",
                dependencies=("hybrid",),
                healthcheck="ok",
                version="0.1.0",
                source="skill",
            ),
        ),
    )


def _router() -> AgentScopeRouter:
    return AgentScopeRouter(
        model_config=ModelConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        )
    )


def test_router_maps_llm_decision_to_candidates(monkeypatch) -> None:
    router = _router()

    monkeypatch.setattr(
        router,
        "_llm_route",
        lambda query, snapshot: RouteDecision(
            scene="finance",
            required_capabilities=["finance.analysis", "planning.decompose"],
            candidate_ids=["finance-router-agent"],
            reasoning="budget analysis",
        ),
    )

    result = router.route("请帮我分析预算", _snapshot())

    assert result.ok
    assert result.data["scene"] == "finance"
    assert "finance.analysis" in result.data["required_capabilities"]
    assert result.data["candidates"][0]["id"] == "finance-router-agent"


def test_router_fails_for_empty_query() -> None:
    result = _router().route("   ", _snapshot())

    assert not result.ok
    assert "query is empty" in (result.error or "")


def test_router_falls_back_to_capability_search_when_candidate_ids_empty(monkeypatch) -> None:
    router = _router()

    monkeypatch.setattr(
        router,
        "_llm_route",
        lambda query, snapshot: RouteDecision(
            scene="research",
            required_capabilities=["research.rag"],
            candidate_ids=[],
            reasoning="need rag",
        ),
    )

    result = router.route("请做调研", _snapshot())

    assert result.ok
    assert result.data["scene"] == "research"
    assert result.data["candidates"][0]["id"] == "market-rag-skill"
