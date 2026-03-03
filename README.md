# AgentScope Adaptive Orchestrator

基于 Python 的自适应编排 Agent 骨架，包含：

- Orchestrator 主循环（route -> plan -> execute -> heal）
- 配置驱动注册表与热加载（原子切换 + 回滚）
- RAG 混合检索（关键词 + 向量，向量故障自动降级）
- 基础可观测指标与失败分类/自愈策略

## 快速运行

```bash
PYTHONPATH=src python3 -m main "请做预算分析并生成方案"
```

## 启用 AgentScope ReAct 执行器

默认使用降级执行器（不调用外部模型）。如需启用真实 AgentScope ReActAgent：

```bash
export AGENTSCOPE_EXECUTOR_ENABLED=1
export AGENTSCOPE_MODEL_PROVIDER=openai
export AGENTSCOPE_MODEL_NAME=gpt-4o-mini
export OPENAI_API_KEY=your_api_key
PYTHONPATH=src python3 -m main "请做预算分析并生成方案"
```
