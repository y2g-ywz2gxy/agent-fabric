# -*- coding: utf-8 -*-
"""
自适应编排器主入口模块（多轮 REPL 模式）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.model_config import load_model_config
from observability.metrics import MetricsCollector
from orchestrator.agentscope_executor import AgentScopeReActExecutor
from orchestrator.agentscope_runtime import JSONSessionStore, OrchestratorSessionState
from orchestrator.healing import LLMFailureClassifier, LLMSelfHealer
from orchestrator.planner import AgentScopePlanner
from orchestrator.router import AgentScopeRouter
from orchestrator.runtime import AdaptiveOrchestratorRuntime
from registry.hot_reload import RegistryHotReloader
from registry.transaction import RegistryTransactionManager


def build_runtime(
    config_root: Path,
) -> tuple[AdaptiveOrchestratorRuntime, RegistryTransactionManager, RegistryHotReloader]:
    """构建运行时实例。"""
    agent_registry = config_root / "agents" / "registry.yaml"
    skill_registry = config_root / "skills" / "registry.yaml"
    model_config_path = config_root / "model.yaml"

    manager = RegistryTransactionManager(agent_registry, skill_registry)
    reloader = RegistryHotReloader(manager)
    model_config = load_model_config(model_config_path)

    classifier = LLMFailureClassifier(model_config=model_config)
    healer = LLMSelfHealer(classifier, model_config=model_config, max_rounds=3)

    runtime = AdaptiveOrchestratorRuntime(
        router=AgentScopeRouter(model_config=model_config),
        planner=AgentScopePlanner(model_config=model_config),
        executor=AgentScopeReActExecutor(model_config=model_config),
        healer=healer,
        metrics=MetricsCollector(),
    )
    return runtime, manager, reloader


def run_turn(
    query: str,
    *,
    runtime: AdaptiveOrchestratorRuntime,
    manager: RegistryTransactionManager,
    reloader: RegistryHotReloader,
) -> dict[str, object]:
    """执行单轮查询，并返回结构化输出。"""
    reloader.scan_and_reload(force=False)
    snapshot = manager.get_snapshot()
    result = runtime.run(query, snapshot)

    route_data = dict(runtime.last_context.route_data or {}) if runtime.last_context else {}
    plan_data = dict(runtime.last_context.plan_data or {}) if runtime.last_context else {}

    return {
        "status": result.status.value,
        "next_action": result.next_action,
        "error": result.error,
        "data": dict(result.data),
        "route_data": route_data,
        "plan_data": plan_data,
        "state_history": [state.value for state in runtime.state_machine.history],
    }


def cli() -> None:
    """REPL CLI 入口。"""
    parser = argparse.ArgumentParser(description="Adaptive orchestrator runtime (REPL mode)")
    parser.add_argument(
        "--config-root",
        default="configs",
        help="Config root folder (contains agents/registry.yaml, skills/registry.yaml and model.yaml)",
    )
    parser.add_argument("--session-id", default="default", help="Session id for JSON session persistence")
    parser.add_argument("--user-id", default="", help="Optional user id used for session file names")
    parser.add_argument("--sessions-dir", default=".sessions", help="Directory to store JSON session files")
    args = parser.parse_args()

    runtime, manager, reloader = build_runtime(Path(args.config_root))
    reloader.scan_and_reload(force=True)

    session_state = OrchestratorSessionState()
    session_store = JSONSessionStore(
        session_id=args.session_id,
        user_id=args.user_id,
        save_dir=Path(args.sessions_dir),
    )
    session_store.load(session_state)

    print(
        json.dumps(
            {
                "event": "session_loaded",
                "session_id": args.session_id,
                "turn_count": session_state.turn_count,
            },
            ensure_ascii=False,
        )
    )

    while True:
        try:
            query = input(">>> ").strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            break

        if not query:
            continue
        if query.lower() in {"exit", "quit", "/exit"}:
            break

        output = run_turn(
            query,
            runtime=runtime,
            manager=manager,
            reloader=reloader,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))

        session_state.record_turn(
            query=query,
            response=output,
            route_data=dict(output.get("route_data", {})),
            plan_data=dict(output.get("plan_data", {})),
            state_history=[str(item) for item in output.get("state_history", [])],
        )
        session_store.save(session_state)


if __name__ == "__main__":
    cli()
