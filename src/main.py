# -*- coding: utf-8 -*-
"""Adaptive orchestrator main entry (conversation-first REPL)."""
from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from config.model_config import load_model_config
from config.runtime_config import RuntimeConfig, load_runtime_config
from orchestrator.agentscope_executor import AgentScopeReActExecutor
from orchestrator.agentscope_runtime import JSONSessionStore, OrchestratorSessionState
from orchestrator.orchestrator_session_runtime import OrchestratorSessionRuntime
from orchestrator.registration_agent import RegistrationAssistantAgent
from orchestrator.system_intent_router import SystemIntentRouter
from registry.auto_indexer import RegistryAutoIndexer
from registry.builtin_provider import BuiltinRegistryProvider
from registry.hot_reload import RegistryHotReloader
from registry.registrar import RegistryRegistrar
from registry.schema import RegistryEntry, RegistrySnapshot
from registry.transaction import RegistryTransactionManager


@dataclass(slots=True, frozen=True)
class RegisterCommand:
    source: str
    mode: str  # path | text | invalid
    value: str
    error: str = ""


def build_session_runtime(
    config_root: Path,
    *,
    runtime_config: RuntimeConfig,
    model_config,
) -> tuple[OrchestratorSessionRuntime, RegistryTransactionManager, RegistryHotReloader]:
    """Build conversation runtime with dynamic integration refresh."""
    agent_registry = config_root / "agents" / "registry.yaml"
    skill_registry = config_root / "skills" / "registry.yaml"

    manager = RegistryTransactionManager(agent_registry, skill_registry)
    reloader = RegistryHotReloader(manager)
    indexer = RegistryAutoIndexer(config_root)
    builtin_provider = BuiltinRegistryProvider(project_root=Path.cwd())

    executor = AgentScopeReActExecutor(
        model_config=model_config,
        max_parallel=runtime_config.execution.max_parallel,
        fail_fast=runtime_config.execution.fail_fast,
    )

    runtime = OrchestratorSessionRuntime(
        executor=executor,
        manager=manager,
        reloader=reloader,
        indexer=indexer,
        builtin_provider=builtin_provider,
    )
    return runtime, manager, reloader


def cli() -> None:
    """REPL CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Adaptive orchestrator runtime (conversation-first REPL)")
    parser.add_argument(
        "--config-root",
        default="configs",
        help="Config root folder (contains agents/registry.yaml, skills/registry.yaml and model.yaml)",
    )
    parser.add_argument("--session-id", default="", help="Explicit new session id")
    parser.add_argument("--resume-session-id", default="", help="Resume an existing session id")
    parser.add_argument("--user-id", default="", help="Optional user id used for session file names")
    parser.add_argument("--sessions-dir", default="", help="Directory to store JSON session files")
    parser.add_argument("--mode", default="", help="orchestrator_agent | legacy_pipeline")
    parser.add_argument("--json-events", action="store_true", help="Emit JSON events instead of text stream")
    args = parser.parse_args()

    config_root = Path(args.config_root)
    model_config = load_model_config(config_root / "model.yaml")
    runtime_config = load_runtime_config(config_root / "runtime.yaml")

    mode = (args.mode.strip().lower() or runtime_config.mode)
    if mode not in {"orchestrator_agent", "legacy_pipeline"}:
        mode = "orchestrator_agent"

    output_format = "json_events" if args.json_events else runtime_config.output_format
    if output_format not in {"text_stream", "json_events"}:
        output_format = "text_stream"

    if args.session_id and args.resume_session_id:
        raise SystemExit("--session-id and --resume-session-id are mutually exclusive")

    session_mode = "new"
    session_id = args.session_id.strip()
    if args.resume_session_id.strip():
        session_mode = "resume"
        session_id = args.resume_session_id.strip()
    if not session_id:
        session_id = _new_session_id()

    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else Path(runtime_config.session.sessions_dir)
    session_store = JSONSessionStore(
        session_id=session_id,
        user_id=args.user_id,
        save_dir=sessions_dir,
    )

    if session_mode == "new" and args.session_id and session_store.session_file_path().exists():
        raise SystemExit(f"session already exists: {session_store.session_file_path()}")

    while session_mode == "new" and not args.session_id and session_store.session_file_path().exists():
        session_id = _new_session_id()
        session_store = JSONSessionStore(
            session_id=session_id,
            user_id=args.user_id,
            save_dir=sessions_dir,
        )

    runtime, manager, reloader = build_session_runtime(
        config_root,
        runtime_config=runtime_config,
        model_config=model_config,
    )

    startup_sync = runtime.indexer.sync(force=True)
    reloader.scan_and_reload(force=True)
    runtime.executor.refresh_integrations(runtime.runtime_snapshot())

    intent_router = SystemIntentRouter(model_config=model_config)
    mock_user = _prompt_mock_user()
    registration_agent = RegistrationAssistantAgent(model_config=model_config)

    audit_dir = Path(runtime_config.registration.audit_dir)
    if not audit_dir.is_absolute():
        audit_dir = Path.cwd() / audit_dir
    registrar = RegistryRegistrar(manager, audit_dir=audit_dir)

    session_state = OrchestratorSessionState()
    if session_mode == "resume":
        session_store.load(session_state)

    event_payload: dict[str, object] = {
        "event": "session_loaded",
        "session_id": session_id,
        "mode": session_mode,
        "runtime_mode": mode,
        "turn_count": session_state.turn_count,
        "mock_user": mock_user,
        "index_sync_changed": startup_sync.changed,
        "index_sync_errors": list(startup_sync.errors),
    }
    if session_mode == "resume":
        event_payload["resume_preview"] = session_state.recent_trace(
            runtime_config.session.resume_preview_turns
        )
    print(json.dumps(event_payload, ensure_ascii=False))

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

        register_cmd = _parse_register_command(query)
        if register_cmd is not None:
            if mock_user != "admin":
                denied = registrar.audit_denied(
                    source=register_cmd.source,
                    actor=mock_user,
                    session_id=session_id,
                    message="permission denied: only admin can register",
                )
                print(
                    json.dumps(
                        {
                            "event": "registration_denied",
                            "source": register_cmd.source,
                            "message": denied.message,
                            "audit": denied.audit_path,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            if register_cmd.mode == "invalid":
                failed = registrar.audit_failed(
                    source=register_cmd.source,
                    actor=mock_user,
                    session_id=session_id,
                    message=register_cmd.error or "invalid register command",
                )
                print(
                    json.dumps(
                        {
                            "event": "registration_failed",
                            "source": register_cmd.source,
                            "error": failed.message,
                            "audit": failed.audit_path,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            try:
                entry: dict[str, object]
                extra_payload: dict[str, object] = {}
                if register_cmd.source == "agent":
                    if register_cmd.mode != "path":
                        raise ValueError("register-agent only supports --path <file.py>")
                    agent_path = _resolve_user_path(register_cmd.value)
                    entry = registration_agent.build_agent_entry_from_path(agent_path)
                elif register_cmd.mode == "path":
                    skill_path = _resolve_user_path(register_cmd.value)
                    entry = registration_agent.build_skill_entry_from_path(skill_path)
                else:
                    entry, skill_dir = registration_agent.create_skill_from_requirement(
                        requirement_text=register_cmd.value,
                        output_root=config_root / "skills",
                    )
                    extra_payload["generated_skill_dir"] = str(skill_dir)
            except Exception as exc:
                failed = registrar.audit_failed(
                    source=register_cmd.source,
                    actor=mock_user,
                    session_id=session_id,
                    message=f"registration intake failed: {exc}",
                )
                print(
                    json.dumps(
                        {
                            "event": "registration_failed",
                            "source": register_cmd.source,
                            "error": failed.message,
                            "audit": failed.audit_path,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            result = registrar.register(
                source=register_cmd.source,
                entry=entry,
                actor=mock_user,
                session_id=session_id,
            )
            print(
                json.dumps(
                    {
                        "event": "registration_result",
                        "success": result.success,
                        "source": result.source,
                        "entry_id": result.entry_id,
                        "message": result.message,
                        "changed_files": list(result.changed_files),
                        "audit": result.audit_path,
                        **extra_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

            if result.success:
                runtime.indexer.sync(force=True)
                reloader.scan_and_reload(force=True)
                refresh = runtime.executor.refresh_integrations(runtime.runtime_snapshot())
                print(
                    json.dumps(
                        {
                            "event": "runtime_refreshed",
                            **refresh,
                        },
                        ensure_ascii=False,
                    )
                )
            continue

        intent = intent_router.detect(query)
        if intent.intent == "list_integrations":
            if mock_user != "admin":
                print(
                    json.dumps(
                        {
                            "event": "permission_denied",
                            "action": "list_integrations",
                            "message": "permission denied: only admin can query integrated agents/skills",
                        },
                        ensure_ascii=False,
                    )
                )
                continue
            snapshot = runtime.runtime_snapshot()
            print(json.dumps(_list_integrations_payload(snapshot), ensure_ascii=False, indent=2))
            continue

        try:
            if mode == "legacy_pipeline":
                output = {
                    "status": "failed",
                    "next_action": "abort",
                    "error": "legacy_pipeline is reserved for compatibility; use orchestrator_agent mode.",
                    "data": {},
                    "route_data": {},
                    "plan_data": {},
                    "state_history": ["initialized", "failed"],
                    "index_sync_errors": [],
                }
            else:
                output = runtime.run_turn_stream(
                    query,
                    stream=output_format == "text_stream",
                )
        except Exception as exc:
            output = {
                "status": "failed",
                "next_action": "abort",
                "error": f"turn execution error: {exc}",
                "data": {},
                "route_data": {},
                "plan_data": {},
                "state_history": ["initialized", "failed"],
                "index_sync_errors": [],
            }

        if output_format == "json_events":
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if output.get("status") == "failed":
                print(f"[error] {output.get('error')}")

        session_state.record_turn(
            query=query,
            response=output,
            route_data=dict(output.get("route_data", {})),
            plan_data=dict(output.get("plan_data", {})),
            state_history=[str(item) for item in output.get("state_history", [])],
        )
        try:
            session_store.save(session_state)
        except Exception as exc:
            print(f"[warn] session save failed: {exc}")


def _new_session_id() -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"sess-{now}-{uuid4().hex[:8]}"


def _prompt_mock_user() -> str:
    try:
        raw = input("login user (admin/user) [user]: ").strip().lower()
    except EOFError:
        return "user"
    if raw in {"admin", "user"}:
        return raw
    return "user"


def _parse_register_command(query: str) -> RegisterCommand | None:
    if not query.startswith("/register-agent") and not query.startswith("/register-skill"):
        return None
    try:
        parts = shlex.split(query)
    except ValueError as exc:
        source = "agent" if query.startswith("/register-agent") else "skill"
        return RegisterCommand(source=source, mode="invalid", value="", error=str(exc))

    if not parts:
        return None
    cmd = parts[0]
    if cmd == "/register-agent":
        if len(parts) < 3 or parts[1] != "--path":
            return RegisterCommand(
                source="agent",
                mode="invalid",
                value="",
                error="usage: /register-agent --path <file.py>",
            )
        return RegisterCommand(source="agent", mode="path", value=parts[2])

    if cmd == "/register-skill":
        if len(parts) >= 3 and parts[1] == "--path":
            return RegisterCommand(source="skill", mode="path", value=parts[2])
        text = query[len("/register-skill") :].strip()
        if not text:
            return RegisterCommand(
                source="skill",
                mode="invalid",
                value="",
                error="usage: /register-skill --path <skill_dir|SKILL.md> OR /register-skill <requirement>",
            )
        return RegisterCommand(source="skill", mode="text", value=text)
    return None


def _resolve_user_path(raw: str) -> Path:
    normalized = raw.strip().replace("\\", "/")
    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _serialize_entry(entry: RegistryEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "source": entry.source,
        "origin": entry.origin,
        "description": entry.description,
        "capabilities": list(entry.capabilities),
        "version": entry.version,
        "loader_kind": entry.loader_kind,
        "loader_target": entry.loader_target,
        "entrypoint": entry.entrypoint,
    }


def _list_integrations_payload(snapshot: RegistrySnapshot) -> dict[str, object]:
    agents = sorted((_serialize_entry(item) for item in snapshot.agents), key=lambda x: str(x["id"]))
    skills = sorted((_serialize_entry(item) for item in snapshot.skills), key=lambda x: str(x["id"]))
    return {
        "event": "integrations_list",
        "summary": {
            "agents": len(agents),
            "skills": len(skills),
            "total": len(agents) + len(skills),
        },
        "agents": agents,
        "skills": skills,
    }


if __name__ == "__main__":
    cli()
