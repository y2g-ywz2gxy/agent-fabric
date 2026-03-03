# AgentScope Adaptive Orchestrator

基于 Python 的 AgentScope-first 编排系统，默认采用单编排主智能体模式，包含：

- 编排主智能体（唯一用户入口）
- PlanNotebook 主计划能力（create/update/finish 子任务与计划）
- 子智能体/技能工具化调用（registry -> toolkit）
- 注册表热加载、会话持久化（JSONSession）

## 快速运行（多轮 REPL）

```bash
PYTHONPATH=src python3 -m main \
  --config-root configs
```

默认输出为文本流式；可加 `--json-events` 输出结构化事件。

退出命令：`exit` / `quit` / `/exit`

恢复历史会话（仅展示最近 N 轮摘要，N 来自 `configs/runtime.yaml`）：

```bash
PYTHONPATH=src python3 -m main \
  --config-root configs \
  --resume-session-id <session_id>
```

REPL 内动态注册命令（仅 `admin` mock 用户可执行）：

- `/register-agent --path <file.py>`
- `/register-skill --path <skill_dir|SKILL.md>`
- `/register-skill <需求文本>`（调用内置 creator-skill 生成 SKILL.md 后注册）

自然语言查询主 Agent 已集成能力（仅 `admin`）：

- 示例：`查看主Agent集成了哪些智能体和skill`

## 动态扫描目录

启动与运行期间会自动扫描并同步：

- `configs/agents/**/*.py`
- `configs/skills/**/SKILL.md`

`src/orchestrator/skills/skill-creator/SKILL.md` 作为内置 builtin skill 注入，不走动态注册。
`src/orchestrator/sub_agents/*.py` 作为内置 advisor 子智能体注入主编排器（route/planner/healing）。

## Agent 代码示例

动态 agent 文件需定义 `AGENT_META` 和 `run(payload)`：

```python
AGENT_META = {
    "id": "support-agent",
    "description": "Handle support triage and troubleshooting tasks",
    "capabilities": ["support.triage", "support.resolve"],
    "version": "0.1.0",
    "dependencies": [],
    "healthcheck": "python -m healthcheck.support_agent",
}


def run(payload):
    task = payload.get("task", "")
    context = payload.get("context", {})
    return {
        "handled": True,
        "task": task,
        "context_keys": sorted(context.keys()),
    }
```

## 模型配置

在 `configs/model.yaml` 中配置 provider / model / api_key；
当配置不可用时，运行时会严格失败，不使用规则兜底。

## 动态注册示例

可运行示例脚本，演示“代码定义 agent + SKILL.md”双注册并持久化：

```bash
PYTHONPATH=src python3 examples/dynamic_orchestrator_registration.py
```
