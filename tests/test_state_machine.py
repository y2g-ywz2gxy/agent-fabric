from __future__ import annotations

from observability.metrics import MetricsCollector
from orchestrator.planner import AdaptivePlanner
from orchestrator.router import KeywordRouter
from orchestrator.runtime import AdaptiveOrchestratorRuntime, RuleBasedExecutor
from orchestrator.state import InvalidStateTransition, RuntimeState, RuntimeStateMachine
from recovery.classifier import FailureClassifier
from recovery.healer import SelfHealer
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
        ),
        skills=(
            RegistryEntry(
                id="general-assistant-skill",
                capabilities=("general.assistant",),
                entrypoint="skills.general:run",
                dependencies=("core-runtime",),
                healthcheck="ok",
                version="0.1.0",
                source="skill",
            ),
        ),
    )


def test_state_machine_accepts_valid_transition_path() -> None:
    machine = RuntimeStateMachine()
    machine.transition_to(RuntimeState.ROUTING)
    machine.transition_to(RuntimeState.PLANNING)
    machine.transition_to(RuntimeState.EXECUTING)
    machine.transition_to(RuntimeState.COMPLETED)

    assert machine.state is RuntimeState.COMPLETED
    assert machine.history == (
        RuntimeState.INITIALIZED,
        RuntimeState.ROUTING,
        RuntimeState.PLANNING,
        RuntimeState.EXECUTING,
        RuntimeState.COMPLETED,
    )


def test_state_machine_rejects_invalid_transition() -> None:
    machine = RuntimeStateMachine()
    machine.transition_to(RuntimeState.ROUTING)

    try:
        machine.transition_to(RuntimeState.EXECUTING)
    except InvalidStateTransition as exc:
        assert "routing -> executing" in str(exc)
    else:
        raise AssertionError("Expected InvalidStateTransition")


def test_runtime_follows_route_plan_execute_state_path() -> None:
    metrics = MetricsCollector()
    runtime = AdaptiveOrchestratorRuntime(
        router=KeywordRouter(),
        planner=AdaptivePlanner(),
        executor=RuleBasedExecutor(),
        healer=SelfHealer(FailureClassifier(), max_rounds=3),
        metrics=metrics,
    )

    result = runtime.run("请做一份预算分析报告", _snapshot())

    assert result.ok
    assert runtime.state_machine.state is RuntimeState.COMPLETED
    assert RuntimeState.ROUTING in runtime.state_machine.history
    assert RuntimeState.PLANNING in runtime.state_machine.history
    assert RuntimeState.EXECUTING in runtime.state_machine.history
    assert "agentscope_plan" in result.data["plan"]
    assert metrics.counter("routing.completed") == 1
    assert metrics.counter("planning.completed") == 1
    assert metrics.counter("execution.completed") == 1


def test_runtime_can_replan_after_planning_failure() -> None:
    metrics = MetricsCollector()
    runtime = AdaptiveOrchestratorRuntime(
        router=KeywordRouter(),
        planner=AdaptivePlanner(fail_first_n=1),
        executor=RuleBasedExecutor(),
        healer=SelfHealer(FailureClassifier(), max_rounds=3),
        metrics=metrics,
    )

    result = runtime.run("请做市场调研总结", _snapshot())

    assert result.ok
    assert metrics.counter("healing.success") >= 1
    assert metrics.counter("planning.completed") >= 2
