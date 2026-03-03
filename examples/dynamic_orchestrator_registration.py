# -*- coding: utf-8 -*-
"""Example: dynamically register persistent agent/skill integrations."""
from __future__ import annotations

import textwrap
from pathlib import Path

from registry.registrar import RegistryRegistrar
from registry.transaction import RegistryTransactionManager


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def main() -> None:
    config_root = Path("configs").resolve()
    agents_registry = config_root / "agents" / "registry.yaml"
    skills_registry = config_root / "skills" / "registry.yaml"

    manager = RegistryTransactionManager(agents_registry, skills_registry)
    registrar = RegistryRegistrar(manager, audit_dir=config_root / "audit")

    agent_file = config_root / "agents" / "dynamic" / "demo_react_agent.py"
    _write(
        agent_file,
        '''
        AGENT_META = {
            "id": "demo-react-agent",
            "description": "Demo react-style sub-agent defined in code",
            "capabilities": ["demo.react"],
            "version": "0.1.0",
            "dependencies": [],
            "healthcheck": "python -m healthcheck.demo_react_agent",
        }


        def run(payload):
            task = payload.get("task", "")
            context = payload.get("context", {})
            return {
                "handled": True,
                "task": task,
                "context_keys": sorted(context.keys()),
                "note": "This is a code-defined dynamic sub-agent.",
            }
        ''',
    )

    agent_result = registrar.register(
        source="agent",
        entry={
            "id": "demo-react-agent",
            "description": "Demo react-style sub-agent defined in code",
            "capabilities": ["demo.react"],
            "entrypoint": f"{agent_file}:run",
            "loader_kind": "python_file",
            "loader_target": f"{agent_file}:run",
            "dependencies": [],
            "healthcheck": "python -m healthcheck.demo_react_agent",
            "version": "0.1.0",
            "origin": "dynamic",
        },
        actor="admin",
        session_id="example-session",
    )

    skill_dir = config_root / "skills" / "demo-skill"
    _write(
        skill_dir / "SKILL.md",
        '''
        ---
        name: demo-skill
        description: Use this skill to generate concise demo summaries.
        metadata:
          capabilities:
            - demo.skill.summary
          version: "0.1.0"
        ---

        ## Usage
        1. Read the user request.
        2. Produce a short structured summary.
        ''',
    )

    skill_result = registrar.register(
        source="skill",
        entry={
            "id": "demo-skill",
            "description": "Use this skill to generate concise demo summaries.",
            "capabilities": ["demo.skill.summary"],
            "entrypoint": str((skill_dir / "SKILL.md").resolve()),
            "loader_kind": "skill_md",
            "loader_target": str((skill_dir / "SKILL.md").resolve()),
            "dependencies": [],
            "healthcheck": "skill-md:demo-skill",
            "version": "0.1.0",
            "origin": "dynamic",
        },
        actor="admin",
        session_id="example-session",
    )

    print("agent registration:", agent_result.success, agent_result.message)
    print("skill registration:", skill_result.success, skill_result.message)


if __name__ == "__main__":
    main()
