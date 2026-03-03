# -*- coding: utf-8 -*-
"""Conversation-first orchestrator runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orchestrator.agentscope_executor import AgentScopeReActExecutor
from registry.auto_indexer import RegistryAutoIndexer
from registry.builtin_provider import BuiltinRegistryProvider
from registry.hot_reload import RegistryHotReloader
from registry.schema import RegistrySnapshot
from registry.transaction import RegistryTransactionManager


@dataclass(slots=True)
class OrchestratorSessionRuntime:
    """Runs one conversational turn with dynamic integration refresh."""

    executor: AgentScopeReActExecutor
    manager: RegistryTransactionManager
    reloader: RegistryHotReloader
    indexer: RegistryAutoIndexer
    builtin_provider: BuiltinRegistryProvider

    def run_turn_stream(self, query: str, *, stream: bool = True) -> dict[str, Any]:
        """Execute one user turn and return structured result payload."""
        index_event = self.indexer.sync(force=False)
        self.reloader.scan_and_reload(force=index_event.changed)
        snapshot = self.runtime_snapshot()
        self.executor.refresh_integrations(snapshot)

        result = self.executor.chat(query, stream=stream)
        data = dict(result.data)
        plan_data = dict(data.get("plan_data", {})) if isinstance(data.get("plan_data"), dict) else {}

        return {
            "status": result.status.value,
            "next_action": result.next_action,
            "error": result.error,
            "data": data,
            "route_data": dict(data.get("route_data", {})) if isinstance(data.get("route_data"), dict) else {},
            "plan_data": plan_data,
            "state_history": list(data.get("state_history", [])) if isinstance(data.get("state_history"), list) else [],
            "index_sync_errors": list(index_event.errors),
        }

    def runtime_snapshot(self) -> RegistrySnapshot:
        """Build snapshot with builtin entries merged in."""
        base = self.manager.get_snapshot()
        existing_ids = {entry.id for entry in base.all_entries}
        builtin = [entry for entry in self.builtin_provider.builtin_entries() if entry.id not in existing_ids]

        agents = list(base.agents)
        skills = list(base.skills)
        for entry in builtin:
            if entry.source == "agent":
                agents.append(entry)
            else:
                skills.append(entry)

        return RegistrySnapshot(
            schema_version=base.schema_version,
            agents=tuple(agents),
            skills=tuple(skills),
            loaded_at=base.loaded_at,
        )
