# -*- coding: utf-8 -*-
"""Registry -> Toolkit bridge for orchestrator agent."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit


@dataclass(slots=True, frozen=True)
class ToolkitRefreshStats:
    """Stats for toolkit refresh operation."""

    entries: int
    callable_tools: int
    agent_skills: int


class ToolkitRegistryBridge:
    """Maintains toolkit tools/skills based on integration snapshot entries."""

    def __init__(
        self,
        *,
        toolkit: Toolkit,
        invoke_entry: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
        list_entries: Callable[[str | None, str | None], list[dict[str, Any]]],
        list_capabilities: Callable[[], dict[str, Any]],
        plan_notebook: PlanNotebook | None = None,
    ) -> None:
        self._toolkit = toolkit
        self._invoke_entry = invoke_entry
        self._list_entries = list_entries
        self._list_capabilities = list_capabilities
        self._plan_notebook = plan_notebook

    def refresh(self, entries: list[Mapping[str, Any]]) -> ToolkitRefreshStats:
        """Rebuild toolkit tools and registered skills from entries."""
        self._toolkit.clear()

        self._toolkit.register_tool_function(self.list_registry_entries)
        self._toolkit.register_tool_function(self.invoke_registry_entry)
        self._toolkit.register_tool_function(self.list_available_capabilities)

        callable_tools = 3
        for entry in entries:
            entry_id = str(entry.get("id", "")).strip()
            if not entry_id:
                continue

            tool_fn = self._make_entry_tool(entry_id)
            self._toolkit.register_tool_function(tool_fn)
            callable_tools += 1

        if self._plan_notebook is not None:
            for tool in self._plan_notebook.list_tools():
                self._toolkit.register_tool_function(tool)
                callable_tools += 1

        registered_skills = 0
        for entry in entries:
            loader_kind = str(entry.get("loader_kind", "")).strip()
            if loader_kind != "skill_md":
                continue
            target = str(entry.get("loader_target") or entry.get("entrypoint") or "").strip()
            if not target:
                continue
            skill_md = Path(target)
            skill_dir = skill_md.parent if skill_md.name == "SKILL.md" else skill_md
            if not skill_dir.exists() or not skill_dir.is_dir():
                continue
            try:
                self._toolkit.register_agent_skill(str(skill_dir))
                registered_skills += 1
            except Exception:
                # Skill metadata may be invalid or duplicated; skip safely.
                continue

        return ToolkitRefreshStats(
            entries=len(entries),
            callable_tools=callable_tools,
            agent_skills=registered_skills,
        )

    def _make_entry_tool(self, entry_id: str) -> Callable[..., dict[str, Any]]:
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", entry_id)
        if not safe or safe[0].isdigit():
            safe = f"entry_{safe}"

        def _tool(task: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
            """Execute a specific registered entry by id."""
            return self._invoke_entry(entry_id, task, context)

        _tool.__name__ = f"entry_{safe}"
        _tool.__qualname__ = _tool.__name__
        return _tool

    def list_registry_entries(
        self,
        capability: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """List currently available registered entries for orchestration."""
        return self._list_entries(capability, source)

    def invoke_registry_entry(
        self,
        entry_id: str,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke one registered entry by id with task/context payload."""
        return self._invoke_entry(entry_id, task, context)

    def list_available_capabilities(self) -> dict[str, Any]:
        """List aggregated capability summary of all current integrations."""
        return self._list_capabilities()
