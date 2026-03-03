# -*- coding: utf-8 -*-
"""
编排器模块

提供自适应编排运行时的核心组件：
- Router: 路由器，负责场景识别和能力匹配
- Planner: 计划器，负责生成执行计划
- Executor: 执行器，负责任务执行
- Healer: 自愈器，负责故障恢复
- RuntimeStateMachine: 状态机，管理运行时状态
"""
from orchestrator.interfaces import Executor, Healer, OrchestrationContext, Planner, Router
from orchestrator.result import ExecutionResult, ExecutionStatus
from orchestrator.runtime import AdaptiveOrchestratorRuntime, RuleBasedExecutor
from orchestrator.state import RuntimeState, RuntimeStateMachine

__all__ = [
    "AdaptiveOrchestratorRuntime",
    "ExecutionResult",
    "ExecutionStatus",
    "Executor",
    "Healer",
    "OrchestrationContext",
    "Planner",
    "Router",
    "RuleBasedExecutor",
    "RuntimeState",
    "RuntimeStateMachine",
]