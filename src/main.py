from __future__ import annotations

import argparse
import json
from pathlib import Path

from observability.metrics import MetricsCollector
from orchestrator.agentscope_executor import AgentScopeReActExecutor
from orchestrator.planner import AdaptivePlanner
from orchestrator.router import KeywordRouter
from orchestrator.runtime import AdaptiveOrchestratorRuntime, RuleBasedExecutor
from recovery.classifier import FailureClassifier
from recovery.healer import SelfHealer
from registry.hot_reload import RegistryHotReloader
from registry.transaction import RegistryTransactionManager


def build_runtime(config_root: Path) -> tuple[AdaptiveOrchestratorRuntime, RegistryTransactionManager, RegistryHotReloader]:
    agent_registry = config_root / "agents" / "registry.yaml"
    skill_registry = config_root / "skills" / "registry.yaml"

    manager = RegistryTransactionManager(agent_registry, skill_registry)
    reloader = RegistryHotReloader(manager)

    runtime = AdaptiveOrchestratorRuntime(
        router=KeywordRouter(),
        planner=AdaptivePlanner(),
        executor=AgentScopeReActExecutor(
            fallback_executor=RuleBasedExecutor(),
        ),
        healer=SelfHealer(FailureClassifier(), max_rounds=3),
        metrics=MetricsCollector(),
    )
    return runtime, manager, reloader


def run_once(query: str, config_root: Path | None = None) -> dict[str, object]:
    config_root = config_root or (Path(__file__).resolve().parent.parent / "configs")
    runtime, manager, reloader = build_runtime(config_root)
    reloader.scan_and_reload(force=True)
    snapshot = manager.get_snapshot()
    result = runtime.run(query, snapshot)

    return {
        "status": result.status.value,
        "next_action": result.next_action,
        "error": result.error,
        "data": dict(result.data),
        "state_history": [state.value for state in runtime.state_machine.history],
    }


def cli() -> None:
    parser = argparse.ArgumentParser(description="Adaptive orchestrator runtime")
    parser.add_argument("query", help="User query for orchestration")
    parser.add_argument(
        "--config-root",
        default="configs",
        help="Config root folder (contains agents/registry.yaml and skills/registry.yaml)",
    )
    args = parser.parse_args()

    output = run_once(args.query, Path(args.config_root))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
