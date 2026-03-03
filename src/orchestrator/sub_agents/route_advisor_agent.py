# -*- coding: utf-8 -*-
"""Route advisor sub-agent entrypoint."""
from __future__ import annotations

from typing import Any, Mapping

from config.model_config import ModelConfig
from orchestrator.result import ExecutionResult
from orchestrator.router import AgentScopeRouter
from registry.schema import RegistryEntry, RegistrySnapshot

AGENT_META = {
    "id": "route-advisor-agent",
    "description": "Suggest candidate capabilities and entries for a query.",
    "capabilities": ["orchestrator.route.advice"],
    "version": "0.1.0",
    "dependencies": [],
    "healthcheck": "python -m healthcheck.route_advisor",
}


def _as_snapshot(entries: list[Mapping[str, Any]]) -> RegistrySnapshot:
    agents: list[RegistryEntry] = []
    skills: list[RegistryEntry] = []
    for raw in entries:
        try:
            entry = RegistryEntry(
                id=str(raw.get("id", "")),
                description=str(raw.get("description", "")),
                capabilities=tuple(str(item) for item in raw.get("capabilities", [])),
                entrypoint=str(raw.get("entrypoint", "")),
                dependencies=tuple(str(item) for item in raw.get("dependencies", [])),
                healthcheck=str(raw.get("healthcheck", "ok")),
                version=str(raw.get("version", "0.1.0")),
                source=str(raw.get("source", "agent")),
                origin=str(raw.get("origin", "dynamic")),
                loader_kind=str(raw.get("loader_kind", "python_module")),
                loader_target=str(raw.get("loader_target") or raw.get("entrypoint", "")),
            )
            if entry.source == "skill":
                skills.append(entry)
            else:
                agents.append(entry)
        except Exception:
            continue

    return RegistrySnapshot(schema_version="1.0", agents=tuple(agents), skills=tuple(skills))


def _fallback_route(query: str, entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    query_lower = query.lower()
    scored: list[tuple[int, Mapping[str, Any]]] = []
    for entry in entries:
        caps = [str(item).lower() for item in entry.get("capabilities", [])]
        score = 0
        for cap in caps:
            token = cap.split(".")[-1]
            if token and token in query_lower:
                score += 2
            if cap in query_lower:
                score += 1
        scored.append((score, entry))

    top = [item for score, item in sorted(scored, key=lambda x: x[0], reverse=True) if score > 0][:5]
    if not top:
        top = entries[:3]

    return {
        "scene": "generic",
        "required_capabilities": sorted({cap for item in top for cap in item.get("capabilities", [])}),
        "matched_capabilities": sorted({cap for item in top for cap in item.get("capabilities", [])}),
        "candidates": top,
        "reasoning": "fallback heuristic routing",
    }


def run(payload: Mapping[str, Any]) -> dict[str, Any]:
    context = payload.get("context", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(context, Mapping):
        context = {}

    query = str(context.get("query") or payload.get("task") or "").strip()
    entries = context.get("registry_entries", [])
    entries = entries if isinstance(entries, list) else []

    config = ModelConfig.from_env()
    if config.is_usable() and entries and query:
        try:
            router = AgentScopeRouter(model_config=config)
            snapshot = _as_snapshot(entries)
            result: ExecutionResult = router.route(query, snapshot)
            return {
                "ok": result.ok,
                "route_data": dict(result.data),
                "error": result.error,
                "next_action": result.next_action,
            }
        except Exception:
            pass

    return {
        "ok": True,
        "route_data": _fallback_route(query, entries),
        "error": None,
        "next_action": "plan",
    }
