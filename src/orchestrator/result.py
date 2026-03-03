from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    next_action: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is ExecutionStatus.SUCCESS

    @classmethod
    def success(
        cls,
        data: Mapping[str, Any] | None = None,
        *,
        next_action: str | None = None,
    ) -> "ExecutionResult":
        return cls(
            status=ExecutionStatus.SUCCESS,
            data=data or {},
            next_action=next_action,
        )

    @classmethod
    def failure(
        cls,
        error: str,
        data: Mapping[str, Any] | None = None,
        *,
        next_action: str | None = None,
    ) -> "ExecutionResult":
        return cls(
            status=ExecutionStatus.FAILED,
            data=data or {},
            error=error,
            next_action=next_action,
        )
