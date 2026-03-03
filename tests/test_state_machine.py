from __future__ import annotations

from observability.metrics import MetricsCollector
from orchestrator.interfaces import OrchestrationContext
from orchestrator.result import ExecutionResult
from orchestrator.runtime import AdaptiveOrchestratorRuntime
from orchestrator.state import InvalidStateTransition, RuntimeState, RuntimeStateMachine
from registry.schema import RegistryEntry, RegistrySnapshot


class _StubRouter:
    def route(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        _ = query
        _ = registry_snapshot
        return ExecutionResult.success(
            {
                "scene": "generic",
                "required_capabilities": ["general.assistant"],
                "matched_capabilities": ["general.assistant"],
                "candidates": [
                    {
                        "id": "general-assistant-skill",
                        "source": "skill",
                        "capabilities": ["general.assistant"],
                        "entrypoint": "skills.general:run",
                        "healthcheck": "ok",
                        "version": "0.1.0",
                    }
                ],
            },
            next_action="plan",
        )


class _StubPlanner:
    def __init__(self, fail_first_n: int = 0) -> None:
        self._fail_first_n = fail_first_n
        self._attempt = 0

    def plan(self, query: str, route_data, *, retry: int = 0) -> ExecutionResult:
        _ = query
        self._attempt += 1
        if self._attempt <= self._fail_first_n:
            return ExecutionResult.failure(
                "Planning failed: simulated planning failure.",
                {"retry": retry},
                next_action="replan",
            )

        return ExecutionResult.success(
            {
                "steps": [{"id": "step-01", "action": "answer", "depends_on": [], "candidates": ["general-assistant-skill"]}],
                "dependencies": {"step-01": []},
                "candidate_entries": list(route_data.get("candidates", [])),
            },
            next_action="execute",
        )


class _StubExecutor:
    def execute(self, query: str, plan_data) -> ExecutionResult:
        _ = plan_data
        return ExecutionResult.success(
            {
                "answer": f"ok:{query}",
                "plan": dict(plan_data),
                "executor": "stub",
            },
            next_action="completed",
        )


class _StubHealer:
    def heal(self, failed_result: ExecutionResult, context: OrchestrationContext, *, attempt: int) -> ExecutionResult:
        _ = context
        if failed_result.next_action == "replan":
            return ExecutionResult.success({"attempt": attempt}, next_action="replan")
        return ExecutionResult.failure("abort", {"attempt": attempt}, next_action="abort")


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


def test_state_machine_allows_healing_to_routing() -> None:
    machine = RuntimeStateMachine()
    machine.transition_to(RuntimeState.ROUTING)
    machine.transition_to(RuntimeState.HEALING)
    machine.transition_to(RuntimeState.ROUTING)

    assert machine.state is RuntimeState.ROUTING


def test_runtime_follows_route_plan_execute_state_path() -> None:
    metrics = MetricsCollector()
    runtime = AdaptiveOrchestratorRuntime(
        router=_StubRouter(),
        planner=_StubPlanner(),
        executor=_StubExecutor(),
        healer=_StubHealer(),
        metrics=metrics,
    )

    result = runtime.run("请做一份预算分析报告", _snapshot())

    assert result.ok
    assert runtime.state_machine.state is RuntimeState.COMPLETED
    assert RuntimeState.ROUTING in runtime.state_machine.history
    assert RuntimeState.PLANNING in runtime.state_machine.history
    assert RuntimeState.EXECUTING in runtime.state_machine.history
    assert metrics.counter("routing.completed") == 1
    assert metrics.counter("planning.completed") == 1
    assert metrics.counter("execution.completed") == 1


def test_runtime_can_replan_after_planning_failure() -> None:
    metrics = MetricsCollector()
    runtime = AdaptiveOrchestratorRuntime(
        router=_StubRouter(),
        planner=_StubPlanner(fail_first_n=1),
        executor=_StubExecutor(),
        healer=_StubHealer(),
        metrics=metrics,
    )

    result = runtime.run("请做市场调研总结", _snapshot())

    assert result.ok
    assert metrics.counter("healing.success") >= 1
    assert metrics.counter("planning.completed") >= 2
