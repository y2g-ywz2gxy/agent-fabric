from __future__ import annotations

from config.runtime_config import load_runtime_config
from orchestrator.agentscope_runtime import OrchestratorSessionState


def test_session_state_recent_trace_returns_latest_n() -> None:
    state = OrchestratorSessionState()
    for idx in range(1, 8):
        state.record_turn(
            query=f"q{idx}",
            response={"status": "success", "next_action": "completed", "error": None},
            route_data={},
            plan_data={},
            state_history=["completed"],
        )

    recent = state.recent_trace(5)

    assert len(recent) == 5
    assert recent[0]["turn"] == 3
    assert recent[-1]["turn"] == 7


def test_load_runtime_config_defaults_when_file_missing(tmp_path) -> None:
    cfg = load_runtime_config(tmp_path / "missing.yaml")

    assert cfg.session.resume_preview_turns == 5
    assert cfg.execution.max_parallel == 4
    assert cfg.registration.audit_dir
