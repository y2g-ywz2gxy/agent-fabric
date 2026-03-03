from __future__ import annotations

from orchestrator.agentscope_runtime import JSONSessionStore, OrchestratorSessionState


def test_json_session_store_can_persist_state(tmp_path) -> None:
    state = OrchestratorSessionState()
    state.record_turn(
        query="hello",
        response={"status": "success", "next_action": "completed", "error": None},
        route_data={"scene": "generic"},
        plan_data={"steps": [{"id": "step-01"}]},
        state_history=["initialized", "completed"],
    )

    store = JSONSessionStore(session_id="s1", user_id="u1", save_dir=tmp_path)
    store.save(state)

    loaded = OrchestratorSessionState()
    store.load(loaded)

    assert loaded.turn_count == 1
    assert loaded.last_route_data["scene"] == "generic"
    assert loaded.last_plan_data["steps"][0]["id"] == "step-01"
    assert loaded.conversation_trace[0]["query"] == "hello"
