# -*- coding: utf-8 -*-
"""Planner advisor sub-agent entrypoint."""
from __future__ import annotations

from typing import Any, Mapping

from config.model_config import ModelConfig
from orchestrator.planner import AgentScopePlanner
from orchestrator.result import ExecutionResult

AGENT_META = {
    "id": "planner-advisor-agent",
    "description": "Generate optional plan draft suggestions for complex tasks.",
    "capabilities": ["orchestrator.plan.advice"],
    "version": "0.1.0",
    "dependencies": [],
    "healthcheck": "python -m healthcheck.planner_advisor",
}


def _fallback_plan(query: str, route_data: Mapping[str, Any]) -> dict[str, Any]:
    candidates = [item.get("id") for item in route_data.get("candidates", []) if isinstance(item, Mapping)]
    candidates = [item for item in candidates if isinstance(item, str) and item]
    return {
        "steps": [
            {
                "id": "step-01",
                "action": "analyze_request",
                "depends_on": [],
                "candidates": candidates,
            },
            {
                "id": "step-02",
                "action": "execute_with_tools",
                "depends_on": ["step-01"],
                "candidates": candidates,
            },
            {
                "id": "step-03",
                "action": "summarize_result",
                "depends_on": ["step-02"],
                "candidates": candidates,
            },
        ],
        "reasoning": f"fallback planner for query: {query[:120]}",
    }


def run(payload: Mapping[str, Any]) -> dict[str, Any]:
    context = payload.get("context", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(context, Mapping):
        context = {}

    query = str(context.get("query") or payload.get("task") or "").strip()
    route_data = context.get("route_data", {})
    if not isinstance(route_data, Mapping):
        route_data = {}

    config = ModelConfig.from_env()
    if config.is_usable() and query and route_data:
        try:
            planner = AgentScopePlanner(model_config=config)
            result: ExecutionResult = planner.plan(query, route_data, retry=0)
            return {
                "ok": result.ok,
                "plan_data": dict(result.data),
                "error": result.error,
                "next_action": result.next_action,
            }
        except Exception:
            pass

    return {
        "ok": True,
        "plan_data": _fallback_plan(query, route_data),
        "error": None,
        "next_action": "execute",
    }
