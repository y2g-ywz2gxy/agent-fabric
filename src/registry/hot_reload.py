from __future__ import annotations

from dataclasses import dataclass

from registry.transaction import RegistryTransactionManager


@dataclass(slots=True, frozen=True)
class HotReloadEvent:
    changed: bool
    applied: bool
    rolled_back: bool
    error: str | None = None


class RegistryHotReloader:
    def __init__(self, transaction_manager: RegistryTransactionManager) -> None:
        self._transaction_manager = transaction_manager
        self._last_fingerprint = self._fingerprint()

    def scan_and_reload(self, *, force: bool = False) -> HotReloadEvent:
        current = self._fingerprint()
        changed = force or current != self._last_fingerprint
        if not changed:
            return HotReloadEvent(changed=False, applied=False, rolled_back=False)

        self._last_fingerprint = current
        result = self._transaction_manager.reload()
        return HotReloadEvent(
            changed=True,
            applied=result.success,
            rolled_back=result.rolled_back,
            error=result.error,
        )

    def _fingerprint(self) -> tuple[tuple[int, int], tuple[int, int]]:
        agents = self._safe_stat(self._transaction_manager.agents_registry_path)
        skills = self._safe_stat(self._transaction_manager.skills_registry_path)
        return (agents, skills)

    @staticmethod
    def _safe_stat(path) -> tuple[int, int]:
        try:
            stat_result = path.stat()
            return (stat_result.st_mtime_ns, stat_result.st_size)
        except FileNotFoundError:
            return (-1, -1)
