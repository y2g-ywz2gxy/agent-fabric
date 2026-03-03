from __future__ import annotations

import time
import types

from agentscope.message import Msg

from orchestrator.agentscope_executor import AgentScopeReActExecutor, AgentScopeRuntimeConfig


class _FakeAgent:
    async def __call__(self, msg):
        return Msg(name="assistant", role="assistant", content=f"summary:{msg.content[:20]}")


def test_executor_runs_independent_steps_in_parallel(monkeypatch) -> None:
    executor = AgentScopeReActExecutor(
        runtime_config=AgentScopeRuntimeConfig(
            enabled=True,
            provider="ollama",
            model_name="qwen2.5:latest",
            api_key=None,
        ),
        max_parallel=4,
    )

    starts: dict[str, float] = {}
    module = types.ModuleType("demo_parallel")

    def run(payload):
        ctx = payload["context"]
        step_id = ctx["step_id"]
        starts[step_id] = time.perf_counter()
        time.sleep(0.2)
        return {
            "step": step_id,
            "deps": sorted((ctx.get("dependency_outputs") or {}).keys()),
        }

    module.run = run
    monkeypatch.setattr("importlib.import_module", lambda name: module)
    monkeypatch.setattr(executor, "_ensure_agent", lambda: _FakeAgent())

    result = executor.execute(
        "do parallel",
        {
            "steps": [
                {"id": "step-01", "action": "alpha", "depends_on": [], "candidates": ["demo"]},
                {"id": "step-02", "action": "beta", "depends_on": [], "candidates": ["demo"]},
                {
                    "id": "step-03",
                    "action": "merge",
                    "depends_on": ["step-01", "step-02"],
                    "candidates": ["demo"],
                },
            ],
            "candidate_entries": [
                {
                    "id": "demo",
                    "source": "skill",
                    "capabilities": ["cap"],
                    "entrypoint": "demo_parallel:run",
                    "version": "0.1.0",
                }
            ],
        },
    )

    assert result.ok
    trace = result.data["execution_trace"]
    assert len(trace) == 3
    assert abs(starts["step-01"] - starts["step-02"]) < 0.12

    step_outputs = result.data["step_outputs"]
    deps = step_outputs["step-03"]["result"]["deps"]
    assert deps == ["step-01", "step-02"]
