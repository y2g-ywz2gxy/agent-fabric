from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuntimeState(str, Enum):
    INITIALIZED = "initialized"
    ROUTING = "routing"
    PLANNING = "planning"
    EXECUTING = "executing"
    HEALING = "healing"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.INITIALIZED: {RuntimeState.ROUTING, RuntimeState.FAILED},
    RuntimeState.ROUTING: {RuntimeState.PLANNING, RuntimeState.HEALING, RuntimeState.FAILED},
    RuntimeState.PLANNING: {RuntimeState.EXECUTING, RuntimeState.HEALING, RuntimeState.FAILED},
    RuntimeState.EXECUTING: {RuntimeState.HEALING, RuntimeState.COMPLETED, RuntimeState.FAILED},
    RuntimeState.HEALING: {
        RuntimeState.PLANNING,
        RuntimeState.EXECUTING,
        RuntimeState.COMPLETED,
        RuntimeState.FAILED,
    },
    RuntimeState.COMPLETED: set(),
    RuntimeState.FAILED: set(),
}


class InvalidStateTransition(RuntimeError):
    pass


@dataclass(slots=True)
class RuntimeStateMachine:
    state: RuntimeState = RuntimeState.INITIALIZED
    _history: list[RuntimeState] = field(default_factory=lambda: [RuntimeState.INITIALIZED])

    def transition_to(self, next_state: RuntimeState) -> None:
        allowed = _ALLOWED_TRANSITIONS[self.state]
        if next_state not in allowed:
            raise InvalidStateTransition(
                f"Illegal state transition: {self.state.value} -> {next_state.value}"
            )
        self.state = next_state
        self._history.append(next_state)

    @property
    def history(self) -> tuple[RuntimeState, ...]:
        return tuple(self._history)
