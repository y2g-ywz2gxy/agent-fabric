# -*- coding: utf-8 -*-
"""注册信息补全与 creator-skill 生成助手。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml
from agentscope.agent import ReActAgent
from agentscope.message import Msg
from pydantic import BaseModel, Field

from config.model_config import ModelConfig
from orchestrator.agentscope_runtime import AgentScopeFactory, run_async
from registry.discovery import (
    build_agent_entry_payload,
    build_skill_entry_payload,
    parse_skill_frontmatter,
    slugify,
)


class RegistrationDraft(BaseModel):
    """注册草稿（兼容旧流程）。"""

    id: str | None = Field(default=None, description="registry entry id")
    description: str | None = Field(default=None, description="描述")
    capabilities: list[str] = Field(default_factory=list, description="能力列表")
    entrypoint: str | None = Field(default=None, description="module:function")
    dependencies: list[str] = Field(default_factory=list, description="依赖列表")
    healthcheck: str | None = Field(default=None, description="健康检查命令")
    version: str | None = Field(default=None, description="版本")
    reasoning: str = Field(default="", description="补全说明")


class SkillScaffoldDraft(BaseModel):
    """skill 生成功能的结构化输出。"""

    name: str = Field(description="skill 名称")
    description: str = Field(description="skill 描述")
    capabilities: list[str] = Field(default_factory=list, description="能力列表")
    instructions: str = Field(description="SKILL.md 正文")


class RegistrationAssistantAgent:
    """通过 AgentScope LLM 辅助补全注册字段与生成 SKILL.md。"""

    _REQUIRED_FIELDS = ("id", "capabilities", "entrypoint", "healthcheck", "version")

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        max_rounds: int = 5,
        max_iters: int = 4,
    ) -> None:
        self._factory = AgentScopeFactory(model_config=model_config)
        self._max_rounds = max(1, max_rounds)
        self._max_iters = max_iters
        self._agent: ReActAgent | None = None
        self._skill_creator_agent: ReActAgent | None = None
        self._creator_skill_md = (
            Path(__file__).resolve().parent / "skills" / "skill-creator" / "SKILL.md"
        )

    def collect(
        self,
        *,
        source: str,
        initial_text: str,
        prompt_user: Callable[[str], str],
    ) -> dict[str, object]:
        """交互式补全注册信息（兼容旧命令输入格式）。"""
        self._factory.ensure_usable()

        transcript = initial_text.strip() or "(no details yet)"
        for _ in range(self._max_rounds):
            draft = self._extract(source=source, text=transcript)
            missing = self._missing_fields(draft)
            if not missing:
                return self._normalize_draft(draft)

            question = self._missing_fields_prompt(missing)
            answer = prompt_user(question).strip()
            if not answer:
                raise ValueError(f"registration cancelled: missing fields: {', '.join(missing)}")
            transcript += f"\n补充: {answer}"

        raise ValueError("registration failed: too many clarification rounds")

    def build_agent_entry_from_path(self, agent_path: Path) -> dict[str, object]:
        """从 agent python 文件构建注册 entry。"""
        return build_agent_entry_payload(agent_path)

    def build_skill_entry_from_path(self, skill_path: Path) -> dict[str, object]:
        """从 SKILL.md 或 skill 目录构建注册 entry。"""
        skill_md = self._resolve_skill_md(skill_path)
        return build_skill_entry_payload(skill_md)

    def create_skill_from_requirement(
        self,
        *,
        requirement_text: str,
        output_root: Path,
    ) -> tuple[dict[str, object], Path]:
        """通过内置 creator-skill 风格流程生成 SKILL.md 并返回 entry。"""
        requirement = requirement_text.strip()
        if not requirement:
            raise ValueError("requirement text is empty")

        scaffold = self._build_skill_scaffold(requirement)
        skill_id = slugify(scaffold.name)
        if not skill_id:
            skill_id = "generated-skill"
        skill_dir = output_root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)

        content = self._render_skill_md(scaffold)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")

        entry = build_skill_entry_payload(skill_md)
        return entry, skill_dir

    def _extract(self, *, source: str, text: str) -> RegistrationDraft:
        agent = self._ensure_agent()
        msg = Msg(
            name="user",
            role="user",
            content=(
                f"请抽取 {source} 注册信息。\n"
                "输出字段：id/description/capabilities/entrypoint/dependencies/healthcheck/version。\n"
                "文本如下：\n"
                f"{text}\n"
            ),
        )
        reply = run_async(agent(msg, structured_model=RegistrationDraft))
        metadata = getattr(reply, "metadata", None) or {}
        return RegistrationDraft.model_validate(metadata)

    def _build_skill_scaffold(self, requirement_text: str) -> SkillScaffoldDraft:
        if not self._factory.model_config.is_usable():
            return self._fallback_skill_scaffold(requirement_text)

        skill_guide = ""
        if self._creator_skill_md.exists():
            try:
                skill_guide = self._creator_skill_md.read_text(encoding="utf-8")[:12000]
            except Exception:
                skill_guide = ""

        agent = self._ensure_skill_creator_agent()
        msg = Msg(
            name="user",
            role="user",
            content=(
                "根据用户需求生成一个可注册的 SKILL.md 草案。\n"
                "输出字段 name/description/capabilities/instructions。\n"
                "要求：description 说明触发时机；instructions 给出可执行步骤。\n"
                f"用户需求：{requirement_text}\n\n"
                f"参考 creator-skill 片段：\n{skill_guide}"
            ),
        )
        reply = run_async(agent(msg, structured_model=SkillScaffoldDraft))
        metadata = getattr(reply, "metadata", None) or {}
        try:
            return SkillScaffoldDraft.model_validate(metadata)
        except Exception:
            return self._fallback_skill_scaffold(requirement_text)

    def _ensure_agent(self) -> ReActAgent:
        if self._agent is not None:
            return self._agent

        model, formatter = self._factory.create_model_and_formatter()
        self._agent = ReActAgent(
            name="registration_assistant",
            sys_prompt=(
                "你是注册信息提取助手。请从用户输入中抽取结构化注册字段。"
                "缺失字段保留为空，不要编造。"
            ),
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._agent

    def _ensure_skill_creator_agent(self) -> ReActAgent:
        if self._skill_creator_agent is not None:
            return self._skill_creator_agent

        model, formatter = self._factory.create_model_and_formatter()
        self._skill_creator_agent = ReActAgent(
            name="registration_skill_creator",
            sys_prompt=(
                "你是 skill 生成助手。根据用户需求输出结构化 skill 草案。"
                "内容需符合 SKILL.md 标准 frontmatter + instructions。"
            ),
            model=model,
            formatter=formatter,
            max_iters=self._max_iters,
        )
        return self._skill_creator_agent

    @classmethod
    def _missing_fields(cls, draft: RegistrationDraft) -> list[str]:
        missing: list[str] = []
        if not (draft.id and draft.id.strip()):
            missing.append("id")
        if not draft.capabilities:
            missing.append("capabilities")
        if not (draft.entrypoint and ":" in draft.entrypoint):
            missing.append("entrypoint")
        if draft.healthcheck is None or not draft.healthcheck.strip():
            missing.append("healthcheck")
        if draft.version is None or not draft.version.strip():
            missing.append("version")
        return missing

    @staticmethod
    def _missing_fields_prompt(missing: list[str]) -> str:
        wanted = ", ".join(missing)
        return (
            f"请补充字段: {wanted}\n"
            "示例: id=demo-agent; description=xxx; capabilities=a,b; entrypoint=pkg.mod:run; "
            "dependencies=x,y; healthcheck=python -m healthcheck.demo; version=0.1.0\n> "
        )

    @staticmethod
    def _normalize_draft(draft: RegistrationDraft) -> dict[str, object]:
        return {
            "id": (draft.id or "").strip(),
            "description": (draft.description or "").strip() or (draft.id or "").strip(),
            "capabilities": [item.strip() for item in draft.capabilities if item and item.strip()],
            "entrypoint": (draft.entrypoint or "").strip(),
            "loader_kind": "python_module",
            "loader_target": (draft.entrypoint or "").strip(),
            "dependencies": [item.strip() for item in draft.dependencies if item and item.strip()],
            "healthcheck": (draft.healthcheck or "").strip(),
            "version": (draft.version or "").strip(),
            "origin": "dynamic",
        }

    @staticmethod
    def _resolve_skill_md(skill_path: Path) -> Path:
        path = skill_path.resolve()
        if path.is_dir():
            target = path / "SKILL.md"
        else:
            target = path
        if target.name != "SKILL.md":
            raise ValueError(f"invalid skill path: {skill_path}, expected SKILL.md or skill dir")
        if not target.exists():
            raise FileNotFoundError(f"skill file not found: {target}")
        # 前置校验一次，确保格式可被 registry 识别
        parse_skill_frontmatter(target)
        return target

    @staticmethod
    def _render_skill_md(scaffold: SkillScaffoldDraft) -> str:
        capabilities = [item for item in scaffold.capabilities if item]
        if not capabilities:
            capabilities = [f"skill.{slugify(scaffold.name)}"]
        fm = {
            "name": scaffold.name,
            "description": scaffold.description,
            "metadata": {
                "version": "0.1.0",
                "capabilities": capabilities,
            },
        }
        frontmatter = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
        body = scaffold.instructions.strip() or "## Usage\nFollow the user's request and produce actionable output."
        return f"---\n{frontmatter}\n---\n\n{body}\n"

    @staticmethod
    def _fallback_skill_scaffold(requirement_text: str) -> SkillScaffoldDraft:
        name = slugify(requirement_text[:48])
        return SkillScaffoldDraft(
            name=name,
            description=f"Handle requests related to: {requirement_text[:160]}",
            capabilities=[f"skill.{slugify(name)}"],
            instructions=(
                "## Intent\n"
                "Understand the user's goal and constraints.\n\n"
                "## Steps\n"
                "1. Clarify expected output and assumptions.\n"
                "2. Execute the task with clear intermediate structure.\n"
                "3. Return concise result and next action."
            ),
        )
