# -*- coding: utf-8 -*-
"""AgentScope 执行器。

能力：
- 基于计划 DAG 调度 registry entrypoint
- 同层无依赖步骤并行执行
- 失败快速返回（可配置）
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async
from orchestrator.result import ExecutionResult
from orchestrator.skill_md_adapter import SkillMarkdownAdapter
from orchestrator.toolkit_registry_bridge import ToolkitRegistryBridge
from registry.schema import RegistrySnapshot


@dataclass(slots=True, frozen=True)
class AgentScopeRuntimeConfig:
    """兼容配置对象（用于历史兼容）。"""

    enabled: bool
    provider: str
    model_name: str
    api_key: str | None

    @classmethod
    def from_model_config(cls, config: ModelConfig) -> "AgentScopeRuntimeConfig":
        return cls(
            enabled=config.enabled,
            provider=config.provider,
            model_name=config.model_name,
            api_key=config.api_key,
        )

    @classmethod
    def from_env(cls) -> "AgentScopeRuntimeConfig":
        model_config = ModelConfig.from_env()
        return cls.from_model_config(model_config)

    def is_usable(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "ollama":
            return True
        return bool(self.api_key)


class AgentScopeReActExecutor:
    """计划 DAG 执行器 + 对话式编排主智能体执行器。"""

    def __init__(
        self,
        *,
        model_config: ModelConfig | None = None,
        runtime_config: AgentScopeRuntimeConfig | None = None,
        sys_prompt: str | None = None,
        max_iters: int = 5,
        skills_root: str | Path = "",
        max_parallel: int = 4,
        fail_fast: bool = True,
    ) -> None:
        if model_config is not None:
            self._model_config = model_config
        elif runtime_config is not None:
            self._model_config = ModelConfig(
                enabled=runtime_config.enabled,
                provider=runtime_config.provider,
                model_name=runtime_config.model_name,
                api_key=runtime_config.api_key,
            )
        else:
            self._model_config = ModelConfig.from_env()

        self._factory = AgentScopeFactory(model_config=self._model_config)
        self._max_iters = max_iters if max_iters != 5 else self._model_config.react.max_iters
        self._skills_root = Path(skills_root) if skills_root else None
        self._max_parallel = max(1, max_parallel)
        self._fail_fast = fail_fast

        self._plan_notebook = PlanNotebook(max_subtasks=24)
        self._master_sys_prompt = (
            "你是编排主智能体（唯一面向用户）。\n"
            "规则：\n"
            "1) 复杂任务必须先调用 create_plan。\n"
            "2) 每个子任务开始前调用 update_subtask_state(..., in_progress)。\n"
            "3) 子任务完成后调用 finish_subtask 记录实际产出。\n"
            "4) 全部任务完成后必须调用 finish_plan，再向用户总结。\n"
            "5) 子任务执行通过工具调用具体子 agent / skill。\n"
            "6) 某步失败时，可调用 healing-advisor-agent 归因并决定 retry/replan/abort。\n"
            "请保持输出简洁、可执行。"
        )
        self._sys_prompt = sys_prompt or self._master_sys_prompt

        self._agent: ReActAgent | None = None
        self._candidate_index: dict[str, Mapping[str, Any]] = {}
        self._integration_index: dict[str, Mapping[str, Any]] = {}
        self._integration_snapshot: RegistrySnapshot | None = None
        self._toolkit = Toolkit()
        self._toolkit_bridge = ToolkitRegistryBridge(
            toolkit=self._toolkit,
            invoke_entry=self._invoke_registry_entry,
            list_entries=self._list_registry_entries,
            list_capabilities=self._list_available_capabilities,
            plan_notebook=self._plan_notebook,
        )
        self._skill_md_adapter = SkillMarkdownAdapter(
            model_config=self._model_config,
            max_iters=min(3, self._max_iters),
        )
        self._toolkit_bridge.refresh([])
        self._update_master_prompt([])

    def refresh_integrations(self, snapshot: RegistrySnapshot) -> dict[str, Any]:
        """同步 registry 快照到主智能体工具与能力视图。"""
        self._integration_snapshot = snapshot
        entries = [self._entry_to_payload(item) for item in snapshot.all_entries]
        self._integration_index = {str(entry["id"]): entry for entry in entries if str(entry.get("id", "")).strip()}
        stats = self._toolkit_bridge.refresh(entries)
        self._update_master_prompt(entries)
        return {
            "entries": stats.entries,
            "callable_tools": stats.callable_tools,
            "agent_skills": stats.agent_skills,
        }

    def chat(self, query: str, *, stream: bool = True) -> ExecutionResult:
        """对话式执行（编排主智能体默认路径）。"""
        try:
            self._factory.ensure_usable()
            agent = self._ensure_agent()
            agent.set_console_output_enabled(stream)
            reply = run_async(agent(Msg(name="user", role="user", content=query)))
            text = (reply.get_text_content() or str(reply.content or "")).strip()
            current_plan = self._plan_notebook.current_plan.model_dump() if self._plan_notebook.current_plan else {}
            state_history = ["initialized", "executing"]
            if current_plan:
                state_history.insert(1, "planning")
            state_history.append("completed")
            return ExecutionResult.success(
                {
                    "answer": text,
                    "executor": "agentscope-orchestrator",
                    "plan_data": current_plan,
                    "state_history": state_history,
                    "metadata": getattr(reply, "metadata", {}) or {},
                },
                next_action="completed",
            )
        except Exception as exc:
            return ExecutionResult.failure(
                f"Chat failed: {exc}",
                {
                    "executor": "agentscope-orchestrator",
                    "state_history": ["initialized", "failed"],
                },
                next_action="abort",
            )

    def stream_reply(self, query: str) -> list[str]:
        """流式接口占位：当前依赖 AgentScope 控制台流式输出。"""
        result = self.chat(query, stream=True)
        answer = str(result.data.get("answer", "")) if result.ok else ""
        return [answer] if answer else []

    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        """执行计划。"""
        try:
            self._factory.ensure_usable()
            self._candidate_index = self._build_candidate_index(plan_data)

            # 兼容历史行为：无候选条目时退回旧式 ReAct 执行
            if not self._candidate_index:
                return self._execute_with_react_only(query, plan_data)

            steps = self._normalize_steps(plan_data.get("steps", []))
            if not steps:
                return ExecutionResult.failure(
                    "Execution failed: plan contains no executable steps.",
                    {"plan": dict(plan_data), "executor": "agentscope-react"},
                )

            run_result = self._execute_step_graph(query=query, steps=steps)
            if not run_result["ok"]:
                return ExecutionResult.failure(
                    f"Execution failed: {run_result['error']}",
                    {
                        "plan": dict(plan_data),
                        "executor": "agentscope-react",
                        "execution_trace": run_result["trace"],
                    },
                )

            answer = self._summarize_execution(
                query=query,
                plan_data=plan_data,
                trace=run_result["trace"],
                outputs=run_result["outputs"],
            )
            return ExecutionResult.success(
                {
                    "answer": answer,
                    "plan": dict(plan_data),
                    "executor": "agentscope-react",
                    "execution_trace": run_result["trace"],
                    "step_outputs": run_result["outputs"],
                },
                next_action="completed",
            )
        except Exception as exc:
            return ExecutionResult.failure(
                f"Execution failed: {exc}",
                {
                    "plan": dict(plan_data),
                    "executor": "agentscope-react",
                },
            )

    def _execute_step_graph(self, *, query: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        steps_by_id = {str(step["id"]): step for step in steps}
        for step in steps:
            for dep in step["depends_on"]:
                if dep not in steps_by_id:
                    return {
                        "ok": False,
                        "error": f"unknown dependency {dep} for step {step['id']}",
                        "trace": [],
                        "outputs": {},
                    }

        done: set[str] = set()
        outputs: dict[str, Any] = {}
        trace: list[dict[str, Any]] = []

        while len(done) < len(steps_by_id):
            ready = [
                step
                for step_id, step in steps_by_id.items()
                if step_id not in done and all(dep in done for dep in step["depends_on"])
            ]
            if not ready:
                return {
                    "ok": False,
                    "error": "cyclic or unsatisfied dependencies",
                    "trace": trace,
                    "outputs": outputs,
                }

            layer_ok = True
            layer_error = ""
            layer_results: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=min(self._max_parallel, len(ready))) as pool:
                futures = {
                    pool.submit(self._run_single_step, query=query, step=step, outputs=outputs): step["id"]
                    for step in ready
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        result = {
                            "ok": False,
                            "step_id": futures[future],
                            "error": str(exc),
                            "trace": {
                                "step_id": futures[future],
                                "status": "failed",
                                "error": str(exc),
                            },
                        }

                    layer_results.append(result)
                    trace.append(result["trace"])
                    if not result["ok"]:
                        layer_ok = False
                        layer_error = result["error"]

            for result in sorted(layer_results, key=lambda item: str(item["step_id"])):
                if result["ok"]:
                    done.add(str(result["step_id"]))
                    outputs[str(result["step_id"])] = result["output"]

            if not layer_ok and self._fail_fast:
                return {
                    "ok": False,
                    "error": layer_error or "step failed",
                    "trace": trace,
                    "outputs": outputs,
                }

            # 非 fail-fast 模式也不继续推进失败依赖链
            if not layer_ok:
                return {
                    "ok": False,
                    "error": layer_error or "step failed",
                    "trace": trace,
                    "outputs": outputs,
                }

        return {"ok": True, "error": "", "trace": trace, "outputs": outputs}

    def _run_single_step(
        self,
        *,
        query: str,
        step: Mapping[str, Any],
        outputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        step_id = str(step["id"])
        action = str(step.get("action", step_id))
        started = datetime.now(timezone.utc).isoformat()
        t0 = perf_counter()

        entry_id = self._pick_entry_for_step(step)
        if not entry_id:
            return {
                "ok": False,
                "step_id": step_id,
                "error": f"no candidate entry for step {step_id}",
                "trace": {
                    "step_id": step_id,
                    "action": action,
                    "entry_id": None,
                    "depends_on": list(step.get("depends_on", [])),
                    "status": "failed",
                    "started_at": started,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": round((perf_counter() - t0) * 1000, 2),
                    "error": f"no candidate entry for step {step_id}",
                },
            }

        try:
            dep_outputs = {
                dep_id: outputs.get(dep_id)
                for dep_id in [str(dep) for dep in step.get("depends_on", [])]
            }
            output = self._invoke_registry_entry(
                entry_id,
                action,
                {
                    "query": query,
                    "step_id": step_id,
                    "depends_on": list(step.get("depends_on", [])),
                    "dependency_outputs": dep_outputs,
                },
            )
            trace = {
                "step_id": step_id,
                "action": action,
                "entry_id": entry_id,
                "depends_on": list(step.get("depends_on", [])),
                "status": "success",
                "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((perf_counter() - t0) * 1000, 2),
            }
            return {
                "ok": True,
                "step_id": step_id,
                "output": output,
                "trace": trace,
            }
        except Exception as exc:
            trace = {
                "step_id": step_id,
                "action": action,
                "entry_id": entry_id,
                "depends_on": list(step.get("depends_on", [])),
                "status": "failed",
                "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((perf_counter() - t0) * 1000, 2),
                "error": str(exc),
            }
            return {
                "ok": False,
                "step_id": step_id,
                "error": str(exc),
                "trace": trace,
            }

    def _pick_entry_for_step(self, step: Mapping[str, Any]) -> str | None:
        candidates = [str(item) for item in step.get("candidates", []) if str(item)]
        for candidate in candidates:
            if candidate in self._candidate_index:
                return candidate
        if self._candidate_index:
            return sorted(self._candidate_index.keys())[0]
        return None

    def _summarize_execution(
        self,
        *,
        query: str,
        plan_data: Mapping[str, Any],
        trace: list[dict[str, Any]],
        outputs: Mapping[str, Any],
    ) -> str:
        """使用 ReAct 对执行轨迹做最终汇总；失败时回退结构化文本。"""
        try:
            agent = self._ensure_agent()
            prompt = (
                f"用户目标: {query}\n"
                f"计划: {json.dumps(dict(plan_data), ensure_ascii=False)}\n"
                f"执行轨迹: {json.dumps(trace, ensure_ascii=False)}\n"
                f"步骤输出: {json.dumps(dict(outputs), ensure_ascii=False)}\n"
                "请给出最终结果总结。"
            )
            reply = run_async(agent(Msg(name="user", role="user", content=prompt)))
            text = reply.get_text_content() or str(reply.content)
            if text.strip():
                return text
        except Exception:
            pass

        if outputs:
            last_key = sorted(outputs.keys())[-1]
            return json.dumps(outputs[last_key], ensure_ascii=False)
        return "Execution finished with no output."

    def _execute_with_react_only(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        """历史兼容路径：交给 ReAct 自主执行。"""
        agent = self._ensure_agent()
        reply = run_async(
            agent(
                Msg(
                    name="user",
                    role="user",
                    content=self._build_execution_prompt(query, plan_data),
                )
            )
        )
        text = reply.get_text_content() or str(reply.content)
        return ExecutionResult.success(
            {
                "answer": text,
                "plan": dict(plan_data),
                "executor": "agentscope-react",
                "metadata": getattr(reply, "metadata", {}) or {},
            },
            next_action="completed",
        )

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent

        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="orchestrator_master_agent",
            sys_prompt=self._sys_prompt,
            model=model,
            formatter=formatter,
            toolkit=self._toolkit,
            plan_notebook=self._plan_notebook,
            max_iters=self._max_iters,
        )
        return self._agent

    def _list_registry_entries(
        self,
        capability: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出可用 registry 条目（供 LLM 选用）。"""
        entries = list(self._candidate_index.values()) if self._candidate_index else list(self._integration_index.values())
        if source:
            entries = [entry for entry in entries if str(entry.get("source")) == source]
        if capability:
            entries = [
                entry
                for entry in entries
                if capability in [str(cap) for cap in entry.get("capabilities", [])]
            ]

        result: list[dict[str, Any]] = []
        for entry in entries:
            result.append(
                {
                    "id": entry.get("id"),
                    "source": entry.get("source"),
                    "capabilities": list(entry.get("capabilities", [])),
                    "entrypoint": entry.get("entrypoint"),
                    "description": entry.get("description"),
                    "origin": entry.get("origin", "dynamic"),
                    "loader_kind": entry.get("loader_kind", "python_module"),
                    "loader_target": entry.get("loader_target") or entry.get("entrypoint"),
                    "version": entry.get("version"),
                }
            )
        return result

    def _invoke_registry_entry(
        self,
        entry_id: str,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 registry entrypoint。"""
        entry = self._candidate_index.get(entry_id) or self._integration_index.get(entry_id)
        if entry is None:
            raise ValueError(f"Unknown registry entry id: {entry_id}")

        merged_context = dict(context or {})
        merged_context.setdefault("registry_entries", list(self._integration_index.values()))
        payload = {"task": task, "context": merged_context}
        loader_kind = str(entry.get("loader_kind", "python_module")).strip() or "python_module"
        loader_target = str(entry.get("loader_target") or entry.get("entrypoint", "")).strip()
        if not loader_target:
            raise ValueError(f"Missing loader target for {entry_id}")

        if loader_kind == "python_module":
            func, resolved = self._resolve_python_module_callable(loader_target)
            value = func(payload)
        elif loader_kind == "python_file":
            func, resolved = self._resolve_python_file_callable(loader_target)
            value = func(payload)
        elif loader_kind == "skill_md":
            resolved = str(Path(loader_target).resolve())
            value = self._skill_md_adapter.execute(
                skill_md=Path(loader_target),
                task=task,
                context=merged_context,
            )
        else:
            raise ValueError(f"Unsupported loader_kind for {entry_id}: {loader_kind}")

        if inspect.isawaitable(value):
            value = run_async(value)

        return {
            "entry_id": entry_id,
            "entrypoint": resolved,
            "result": value,
        }

    def _list_available_capabilities(self) -> dict[str, Any]:
        """聚合能力摘要（供主智能体实时感知）。"""
        entries = list(self._integration_index.values())
        capabilities = sorted(
            {
                str(cap)
                for entry in entries
                for cap in entry.get("capabilities", [])
                if str(cap).strip()
            }
        )
        return {
            "entries": len(entries),
            "capabilities": capabilities,
            "agents": [entry.get("id") for entry in entries if entry.get("source") == "agent"],
            "skills": [entry.get("id") for entry in entries if entry.get("source") == "skill"],
        }

    def _update_master_prompt(self, entries: list[Mapping[str, Any]]) -> None:
        lines: list[str] = []
        for entry in entries:
            lines.append(
                f"- id={entry.get('id')}; source={entry.get('source')}; "
                f"caps={list(entry.get('capabilities', []))}; desc={entry.get('description', '')}"
            )
        ability_text = "\n".join(lines) if lines else "- (none)"
        self._sys_prompt = (
            f"{self._master_sys_prompt}\n\n"
            "当前可用子能力（动态刷新）：\n"
            f"{ability_text}\n"
        )
        if self._agent is not None:
            self._agent._sys_prompt = self._sys_prompt  # type: ignore[attr-defined]

    @staticmethod
    def _entry_to_payload(entry: Any) -> dict[str, Any]:
        return {
            "id": entry.id,
            "source": entry.source,
            "origin": entry.origin,
            "description": entry.description,
            "capabilities": list(entry.capabilities),
            "entrypoint": entry.entrypoint,
            "loader_kind": entry.loader_kind,
            "loader_target": entry.loader_target,
            "dependencies": list(entry.dependencies),
            "healthcheck": entry.healthcheck,
            "version": entry.version,
        }

    @staticmethod
    def _resolve_python_module_callable(target: str) -> tuple[Any, str]:
        if ":" not in target:
            raise ValueError(f"Invalid python module target: {target}")
        module_name, func_name = target.split(":", 1)
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        if not callable(func):
            raise TypeError(f"Entrypoint is not callable: {target}")
        return func, target

    @staticmethod
    def _resolve_python_file_callable(target: str) -> tuple[Any, str]:
        if ":" not in target:
            raise ValueError(f"Invalid python file target: {target}")
        file_path, func_name = target.rsplit(":", 1)
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            raise FileNotFoundError(f"Python file target not found: {abs_path}")

        module_name = f"dynamic_agent_{abs_path.stem}_{abs(hash(str(abs_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {abs_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        func = getattr(module, func_name)
        if not callable(func):
            raise TypeError(f"Entrypoint is not callable: {target}")
        return func, f"{abs_path}:{func_name}"

    @staticmethod
    def _build_candidate_index(plan_data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        entries = plan_data.get("candidate_entries", [])
        index: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            entry_id = str(entry.get("id", "")).strip()
            if entry_id:
                index[entry_id] = entry
        return index

    @staticmethod
    def _normalize_steps(raw_steps: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_steps, list):
            return []

        normalized: list[dict[str, Any]] = []
        for raw in raw_steps:
            if not isinstance(raw, Mapping):
                continue
            step_id = str(raw.get("id", "")).strip()
            if not step_id:
                continue
            depends = raw.get("depends_on", [])
            candidates = raw.get("candidates", [])
            normalized.append(
                {
                    "id": step_id,
                    "action": str(raw.get("action", step_id)),
                    "depends_on": [str(item) for item in depends if str(item).strip()],
                    "candidates": [str(item) for item in candidates if str(item).strip()],
                }
            )
        return normalized

    @staticmethod
    def _build_execution_prompt(query: str, plan_data: Mapping[str, Any]) -> str:
        steps = plan_data.get("steps", [])
        step_lines = []
        for step in steps:
            step_lines.append(
                f"- {step.get('id')}: {step.get('action')} (depends_on={step.get('depends_on', [])})"
            )
        steps_text = "\n".join(step_lines) if step_lines else "- no-steps"
        return (
            f"用户目标: {query}\n"
            "你可以使用工具 `list_registry_entries` 和 `invoke_registry_entry` 调度候选单元。\n"
            f"执行计划:\n{steps_text}\n"
            "请执行并给出最终结果。"
        )
