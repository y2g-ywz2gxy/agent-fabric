from __future__ import annotations

from orchestrator.result import ExecutionResult
from registry.schema import RegistryEntry, RegistrySnapshot


class KeywordRouter:
    _SCENE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            "finance",
            ("预算", "报销", "发票", "财务", "成本"),
            ("finance.analysis", "planning.decompose"),
        ),
        (
            "support",
            ("故障", "报错", "无法", "超时", "异常", "修复"),
            ("support.troubleshoot", "recovery.heal"),
        ),
        (
            "research",
            ("调研", "研究", "报告", "竞品", "市场"),
            ("research.rag", "planning.decompose"),
        ),
    )

    def __init__(self, fallback_capability: str = "general.assistant") -> None:
        self._fallback_capability = fallback_capability

    def route(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        normalized = query.strip()
        if not normalized:
            return ExecutionResult.failure("Routing failed: query is empty.")

        scene, required_capabilities = self._infer_scene(normalized)
        matched_entries = registry_snapshot.find_by_capabilities(required_capabilities)

        if matched_entries:
            matched_capabilities = sorted(
                {
                    capability
                    for entry in matched_entries
                    for capability in entry.capabilities
                    if capability in set(required_capabilities)
                }
            )
        else:
            matched_capabilities = [self._fallback_capability]

        payload = {
            "scene": scene,
            "required_capabilities": list(required_capabilities),
            "matched_capabilities": matched_capabilities,
            "candidates": [self._entry_to_payload(entry) for entry in matched_entries],
        }
        return ExecutionResult.success(payload, next_action="plan")

    def _infer_scene(self, query: str) -> tuple[str, tuple[str, ...]]:
        lowered = query.lower()
        for scene, keywords, capabilities in self._SCENE_RULES:
            if any(keyword in lowered for keyword in keywords):
                return scene, capabilities
        return "generic", (self._fallback_capability,)

    @staticmethod
    def _entry_to_payload(entry: RegistryEntry) -> dict[str, object]:
        return {
            "id": entry.id,
            "source": entry.source,
            "capabilities": list(entry.capabilities),
            "entrypoint": entry.entrypoint,
            "healthcheck": entry.healthcheck,
            "version": entry.version,
        }
