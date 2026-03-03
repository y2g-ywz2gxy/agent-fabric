# AgentScope Adaptive Orchestrator

基于 Python 的 AgentScope-first 自适应编排器，包含：

- LLM 路由（route）
- LLM 计划（plan）
- AgentScope ReAct 执行（execute）
- LLM 自愈（heal）
- 注册表热加载、状态机、会话持久化（JSONSession）

## 快速运行（多轮 REPL）

```bash
PYTHONPATH=src python3 -m main \
  --config-root configs \
  --session-id demo \
  --sessions-dir .sessions
```

退出命令：`exit` / `quit` / `/exit`

## 模型配置

在 `configs/model.yaml` 中配置 provider / model / api_key；
当配置不可用时，运行时会严格失败，不使用规则兜底。
