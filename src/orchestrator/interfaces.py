from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from orchestrator.result import ExecutionResult
from registry.schema import RegistrySnapshot


@dataclass(slots=True)
class OrchestrationContext:
    query: str
    registry_snapshot: RegistrySnapshot
    route_data: Mapping[str, Any] | None = None
    plan_data: Mapping[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Router(Protocol):
    def route(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        ...


class Planner(Protocol):
    def plan(
        self,
        query: str,
        route_data: Mapping[str, Any],
        *,
        retry: int = 0,
    ) -> ExecutionResult:
        ...


class Executor(Protocol):
    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        ...


class Healer(Protocol):
    def heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        ...
