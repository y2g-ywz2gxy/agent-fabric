# -*- coding: utf-8 -*-
"""Healing advisor sub-agent entrypoint."""
from __future__ import annotations

from typing import Any, Mapping

from config.model_config import ModelConfig
from orchestrator.healing import LLMFailureClassifier, LLMSelfHealer
from orchestrator.interfaces import OrchestrationContext
from orchestrator.result import ExecutionResult
from registry.schema import RegistrySnapshot

AGENT_META = {
    "id": "healing-advisor-agent",
    "description": "Classify failures and suggest retry/replan/abort actions.",
    "capabilities": ["orchestrator.heal.advice"],
    "version": "0.1.0",
    "dependencies": [],
    "healthcheck": "python -m healthcheck.healing_advisor",
}


def _fallback_heal(error: str) -> dict[str, Any]:
    text = (error or "").lower()
    if "timeout" in text or "temporary" in text:
        action = "retry_execute"
    elif "plan" in text or "dependency" in text:
        action = "replan"
    else:
        action = "abort"
    return {
        "attempt": 0,
        "failure_type": "unknown",
        "reason": "fallback healing suggestion",
        "next_action": action,
    }


def run(payload: Mapping[str, Any]) -> dict[str, Any]:
    context = payload.get("context", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(context, Mapping):
        context = {}

    error = str(context.get("error") or payload.get("task") or "")
    config = ModelConfig.from_env()
    if config.is_usable() and error:
        try:
            classifier = LLMFailureClassifier(model_config=config)
            healer = LLMSelfHealer(classifier, model_config=config)
            failed = ExecutionResult.failure(error, data={"context": dict(context)}, next_action="replan")
            healed = healer.heal(
                failed,
                OrchestrationContext(
                    query=str(context.get("query", "")),
                    registry_snapshot=RegistrySnapshot(schema_version="1.0", agents=(), skills=()),
                    route_data={},
                    plan_data={},
                ),
                attempt=0,
            )
            return {
                "ok": healed.ok,
                "data": dict(healed.data),
                "error": healed.error,
                "next_action": healed.next_action,
            }
        except Exception:
            pass

    fallback = _fallback_heal(error)
    return {
        "ok": True,
        "data": {
            "attempt": fallback["attempt"],
            "failure_type": fallback["failure_type"],
            "reason": fallback["reason"],
        },
        "error": None,
        "next_action": fallback["next_action"],
    }
