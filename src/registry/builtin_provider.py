# -*- coding: utf-8 -*-
"""内置（builtin）agent/skill 条目提供器。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from registry.discovery import parse_skill_frontmatter, slugify
from registry.schema import RegistryEntry


@dataclass(slots=True)
class BuiltinRegistryProvider:
    """收集内置能力并转为 registry entry。"""

    project_root: Path

    def builtin_entries(self) -> tuple[RegistryEntry, ...]:
        entries: list[RegistryEntry] = []
        creator = self.project_root / "src" / "orchestrator" / "skills" / "skill-creator" / "SKILL.md"
        if creator.exists():
            entries.append(self._from_skill_md(creator))
        entries.extend(self._advisor_agent_entries())
        return tuple(entries)

    @staticmethod
    def _from_skill_md(skill_md: Path) -> RegistryEntry:
        frontmatter = parse_skill_frontmatter(skill_md)
        name = str(frontmatter.get("name", "")).strip() or skill_md.parent.name
        skill_id = slugify(name)
        description = str(frontmatter.get("description", "")).strip() or f"builtin:{skill_id}"
        metadata = frontmatter.get("metadata", {})
        caps = []
        if isinstance(metadata, dict):
            raw_caps = metadata.get("capabilities", [])
            if isinstance(raw_caps, list):
                caps = [str(item).strip() for item in raw_caps if str(item).strip()]
            elif isinstance(raw_caps, str):
                caps = [raw_caps.strip()]
        if not caps:
            caps = [f"builtin.skill.{skill_id}"]

        return RegistryEntry(
            id=skill_id,
            description=description,
            capabilities=tuple(caps),
            entrypoint=str(skill_md.resolve()),
            loader_kind="skill_md",
            loader_target=str(skill_md.resolve()),
            dependencies=tuple(),
            healthcheck=f"skill-md:{skill_id}",
            version="builtin",
            source="skill",
            origin="builtin",
        )

    def _advisor_agent_entries(self) -> list[RegistryEntry]:
        advisors: list[tuple[str, str, tuple[str, ...], Path]] = [
            (
                "route-advisor-agent",
                "Suggest candidate capabilities and entries for a query.",
                ("orchestrator.route.advice",),
                self.project_root / "src" / "orchestrator" / "sub_agents" / "route_advisor_agent.py",
            ),
            (
                "planner-advisor-agent",
                "Generate optional plan draft suggestions for complex tasks.",
                ("orchestrator.plan.advice",),
                self.project_root / "src" / "orchestrator" / "sub_agents" / "planner_advisor_agent.py",
            ),
            (
                "healing-advisor-agent",
                "Classify failures and suggest retry/replan/abort actions.",
                ("orchestrator.heal.advice",),
                self.project_root / "src" / "orchestrator" / "sub_agents" / "healing_advisor_agent.py",
            ),
        ]

        entries: list[RegistryEntry] = []
        for entry_id, description, capabilities, py_file in advisors:
            if not py_file.exists():
                continue
            loader_target = f"{py_file.resolve()}:run"
            entries.append(
                RegistryEntry(
                    id=entry_id,
                    description=description,
                    capabilities=capabilities,
                    entrypoint=loader_target,
                    loader_kind="python_file",
                    loader_target=loader_target,
                    dependencies=tuple(),
                    healthcheck=f"python {py_file.name} --healthcheck",
                    version="builtin",
                    source="agent",
                    origin="builtin",
                )
            )

        return entries
