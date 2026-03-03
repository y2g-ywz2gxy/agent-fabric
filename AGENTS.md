# Repository Guidelines

## Project Structure & Module Organization
Core runtime code lives in `src/`, organized by capability:
- `src/orchestrator/`: routing, planning, execution loop, state machine.
- `src/registry/`: config loading, schema, transactions, hot-reload.
- `src/recovery/`, `src/rag/`, `src/observability/`: healing, retrieval, metrics.
- `src/main.py`: CLI entrypoint and runtime wiring.

Tests are under `tests/` (one `test_*.py` module per subsystem). Runtime registries are YAML files in `configs/agents/registry.yaml` and `configs/skills/registry.yaml`. BMAD assets and generated artifacts live in `_bmad/` and `_bmad-output/`.

## Build, Test, and Development Commands
- `python3 -m pip install -e ".[dev]"`: install package in editable mode with pytest.
- `PYTHONPATH=src python3 -m main "<query>"`: run the orchestrator from source.
- `adaptive-orchestrator "<query>" --config-root configs`: run via installed console script.
- `pytest`: run all tests (configured via `pyproject.toml`, quiet mode).
- `pytest tests/test_state_machine.py -q`: run a focused test module.

Optional AgentScope execution requires environment flags such as `AGENTSCOPE_EXECUTOR_ENABLED=1` and provider/model credentials.

## Coding Style & Naming Conventions
Use Python 3.11+ with PEP 8 defaults:
- 4-space indentation, `snake_case` for functions/modules, `PascalCase` for classes.
- Add type hints for public APIs and datatypes passed across modules.
- Keep orchestration results structured (dict-like payloads with explicit keys).
- Follow existing bilingual comment/docstring style where context benefits from Chinese explanations.

No formatter/linter is enforced in-repo yet; keep changes consistent with surrounding code.

## Testing Guidelines
Use `pytest` and place tests in `tests/test_<feature>.py`. Name tests as behavior statements (for example, `test_runtime_can_replan_after_planning_failure`). Cover:
- happy path (`route -> plan -> execute`),
- failure classification/healing,
- registry reload/atomicity edge cases.

No coverage threshold is configured; new behavior should include or update tests.

## Commit & Pull Request Guidelines
Git history is currently minimal (initial commit: `init`), so apply a clear convention going forward:
- Commit message format: short imperative summary, optionally scoped (for example, `orchestrator: add replan retry guard`).
- Keep commits focused and logically grouped.

For PRs, include:
- what changed and why,
- linked issue/task ID,
- test evidence (`pytest` output or targeted test list),
- config/env changes (especially AgentScope-related variables).
