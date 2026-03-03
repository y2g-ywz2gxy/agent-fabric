# -*- coding: utf-8 -*-
"""
自适应编排器主入口模块

该模块提供了自适应编排运行时的入口点，包括：
- 构建和配置运行时组件
- 执行单次查询的编排流程
- 命令行接口 (CLI)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from observability.metrics import MetricsCollector  # 指标收集器，用于记录运行时指标
from orchestrator.agentscope_executor import AgentScopeReActExecutor  # AgentScope ReAct 执行器
from orchestrator.planner import AdaptivePlanner  # 自适应计划器
from orchestrator.router import KeywordRouter  # 关键字路由器
from orchestrator.runtime import AdaptiveOrchestratorRuntime, RuleBasedExecutor  # 运行时和规则执行器
from recovery.classifier import FailureClassifier  # 故障分类器
from recovery.healer import SelfHealer  # 自愈处理器
from registry.hot_reload import RegistryHotReloader  # 注册表热加载器
from registry.transaction import RegistryTransactionManager  # 注册表事务管理器


def build_runtime(config_root: Path) -> tuple[AdaptiveOrchestratorRuntime, RegistryTransactionManager, RegistryHotReloader]:
    """
    构建自适应编排运行时实例
    
    根据配置根目录构建完整的运行时环境，包括：
    - 注册表事务管理器：管理代理和技能的注册表
    - 注册表热加载器：监控配置文件变化并自动重载
    - 自适应编排运行时：核心编排引擎
    
    参数:
        config_root: 配置文件根目录路径
        
    返回:
        元组包含：运行时实例、事务管理器、热加载器
    """
    # 构建代理和技能的注册表文件路径
    agent_registry = config_root / "agents" / "registry.yaml"
    skill_registry = config_root / "skills" / "registry.yaml"

    # 创建注册表事务管理器，确保注册表操作的原子性
    manager = RegistryTransactionManager(agent_registry, skill_registry)
    # 创建热加载器，监控注册表文件变化
    reloader = RegistryHotReloader(manager)

    # 构建自适应编排运行时
    runtime = AdaptiveOrchestratorRuntime(
        router=KeywordRouter(),  # 使用关键字路由器进行意图识别
        planner=AdaptivePlanner(),  # 使用自适应计划器生成执行计划
        executor=AgentScopeReActExecutor(
            fallback_executor=RuleBasedExecutor(),  # AgentScope 不可用时降级到规则执行器
        ),
        healer=SelfHealer(FailureClassifier(), max_rounds=3),  # 自愈处理器，最多3轮
        metrics=MetricsCollector(),  # 指标收集器
    )
    return runtime, manager, reloader


def run_once(query: str, config_root: Path | None = None) -> dict[str, object]:
    """
    执行单次查询编排
    
    完整执行一次查询的编排流程：
    1. 加载配置并构建运行时
    2. 扫描并重载注册表
    3. 执行编排流程
    4. 返回结构化结果
    
    参数:
        query: 用户查询字符串
        config_root: 配置根目录，默认为项目 configs 目录
        
    返回:
        包含状态、下一步动作、错误信息、数据和状态历史的字典
    """
    # 设置默认配置根目录
    config_root = config_root or (Path(__file__).resolve().parent.parent / "configs")
    # 构建运行时组件
    runtime, manager, reloader = build_runtime(config_root)
    # 强制扫描并重载注册表
    reloader.scan_and_reload(force=True)
    # 获取注册表快照
    snapshot = manager.get_snapshot()
    # 执行编排流程
    result = runtime.run(query, snapshot)

    # 返回结构化结果
    return {
        "status": result.status.value,  # 执行状态
        "next_action": result.next_action,  # 下一步动作
        "error": result.error,  # 错误信息
        "data": dict(result.data),  # 结果数据
        "state_history": [state.value for state in runtime.state_machine.history],  # 状态历史
    }


def cli() -> None:
    """
    命令行接口入口点
    
    解析命令行参数并执行单次查询编排，
    将结果以 JSON 格式输出到标准输出。
    """
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="Adaptive orchestrator runtime")
    parser.add_argument("query", help="User query for orchestration")  # 用户查询
    parser.add_argument(
        "--config-root",
        default="configs",
        help="Config root folder (contains agents/registry.yaml and skills/registry.yaml)",
    )
    args = parser.parse_args()

    # 执行查询并输出 JSON 结果
    output = run_once(args.query, Path(args.config_root))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli()
