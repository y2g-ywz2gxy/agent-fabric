from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from registry.config_loader import load_registry_snapshot
from registry.schema import RegistrySnapshot


@dataclass(slots=True, frozen=True)
class TransactionResult:
    success: bool
    snapshot: RegistrySnapshot
    rolled_back: bool
    error: str | None = None


class RegistryTransactionManager:
    def __init__(self, agents_registry_path: str | Path, skills_registry_path: str | Path) -> None:
        self._agents_registry_path = Path(agents_registry_path)
        self._skills_registry_path = Path(skills_registry_path)
        self._lock = RLock()
        self._snapshot = load_registry_snapshot(
            self._agents_registry_path,
            self._skills_registry_path,
        )

    @property
    def agents_registry_path(self) -> Path:
        return self._agents_registry_path

    @property
    def skills_registry_path(self) -> Path:
        return self._skills_registry_path

    def get_snapshot(self) -> RegistrySnapshot:
        with self._lock:
            return self._snapshot

    def reload(self) -> TransactionResult:
        with self._lock:
            previous = self._snapshot
            try:
                staged = load_registry_snapshot(
                    self._agents_registry_path,
                    self._skills_registry_path,
                )
            except Exception as exc:
                return TransactionResult(
                    success=False,
                    snapshot=previous,
                    rolled_back=True,
                    error=str(exc),
                )

            self._snapshot = staged
            return TransactionResult(success=True, snapshot=staged, rolled_back=False)
