from __future__ import annotations

from orchestrator.router import KeywordRouter
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
                capabilities=("support.troubleshoot", "recovery.heal"),
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


def test_router_matches_finance_scene() -> None:
    result = KeywordRouter().route("请帮我分析本月预算成本", _snapshot())

    assert result.ok
    assert result.data["scene"] == "finance"
    assert "finance.analysis" in result.data["required_capabilities"]
    assert result.data["candidates"]


def test_router_matches_support_scene() -> None:
    result = KeywordRouter().route("系统报错，无法登录，需要排障", _snapshot())

    assert result.ok
    assert result.data["scene"] == "support"
    assert "support.troubleshoot" in result.data["required_capabilities"]


def test_router_matches_research_scene() -> None:
    result = KeywordRouter().route("请做竞品调研并输出研究报告", _snapshot())

    assert result.ok
    assert result.data["scene"] == "research"
    assert "research.rag" in result.data["required_capabilities"]
