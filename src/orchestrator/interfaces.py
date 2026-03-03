# -*- coding: utf-8 -*-
"""
编排器接口定义模块

该模块定义了编排器的核心接口协议（Protocol），包括：
- OrchestrationContext: 编排上下文数据类
- Router: 路由器接口
- Planner: 计划器接口
- Executor: 执行器接口
- Healer: 自愈器接口
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from orchestrator.result import ExecutionResult
from registry.schema import RegistrySnapshot


@dataclass(slots=True)
class OrchestrationContext:
    """
    编排上下文数据类
    
    在编排流程中传递的上下文信息，包含查询、注册表快照、
    路由数据、计划数据和元数据。
    
    属性:
        query: 用户查询字符串
        registry_snapshot: 注册表快照
        route_data: 路由结果数据
        plan_data: 计划结果数据
        metadata: 附加元数据
    """
    query: str  # 用户查询
    registry_snapshot: RegistrySnapshot  # 注册表快照
    route_data: Mapping[str, Any] | None = None  # 路由数据
    plan_data: Mapping[str, Any] | None = None  # 计划数据
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据


class Router(Protocol):
    """
    路由器接口协议
    
    定义路由器的标准接口，负责根据用户查询和注册表快照
    确定匹配的能力和候选执行单元。
    """
    def route(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        """
        执行路由
        
        参数:
            query: 用户查询字符串
            registry_snapshot: 注册表快照
            
        返回:
            包含路由结果的 ExecutionResult
        """
        ...


class Planner(Protocol):
    """
    计划器接口协议
    
    定义计划器的标准接口，负责根据查询和路由数据
    生成执行计划。
    """
    def plan(
        self,
        query: str,
        route_data: Mapping[str, Any],
        *,
        retry: int = 0,
    ) -> ExecutionResult:
        """
        生成执行计划
        
        参数:
            query: 用户查询字符串
            route_data: 路由数据
            retry: 重试次数
            
        返回:
            包含执行计划的 ExecutionResult
        """
        ...


class Executor(Protocol):
    """
    执行器接口协议
    
    定义执行器的标准接口，负责根据查询和计划数据
    执行具体的任务。
    """
    def execute(self, query: str, plan_data: Mapping[str, Any]) -> ExecutionResult:
        """
        执行任务
        
        参数:
            query: 用户查询字符串
            plan_data: 执行计划数据
            
        返回:
            包含执行结果的 ExecutionResult
        """
        ...


class Healer(Protocol):
    """
    自愈器接口协议
    
    定义自愈器的标准接口，负责在执行失败时
    提供恢复策略。
    """
    def heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        """
        执行自愈处理
        
        参数:
            failed_result: 失败的执行结果
            context: 编排上下文
            attempt: 当前尝试次数
            
        返回:
            包含自愈结果的 ExecutionResult
        """
        ...
