# -*- coding: utf-8 -*-
"""
运行时状态机模块

该模块定义了编排运行时的状态机和状态类型，包括：
- RuntimeState: 运行时状态枚举
- RuntimeStateMachine: 状态机实现
- InvalidStateTransition: 非法状态转换异常
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuntimeState(str, Enum):
    """
    运行时状态枚举
    
    定义了编排运行时在各阶段的状态：
    - INITIALIZED: 初始化完成
    - ROUTING: 路由阶段
    - PLANNING: 计划阶段
    - EXECUTING: 执行阶段
    - HEALING: 自愈阶段
    - COMPLETED: 完成状态
    - FAILED: 失败状态
    """
    INITIALIZED = "initialized"  # 初始化完成
    ROUTING = "routing"  # 路由阶段
    PLANNING = "planning"  # 计划阶段
    EXECUTING = "executing"  # 执行阶段
    HEALING = "healing"  # 自愈阶段
    COMPLETED = "completed"  # 完成状态
    FAILED = "failed"  # 失败状态


# 允许的状态转换映射表
# 定义了从每个状态可以转换到哪些目标状态
_ALLOWED_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.INITIALIZED: {RuntimeState.ROUTING, RuntimeState.FAILED},  # 初始化后可进入路由或失败
    RuntimeState.ROUTING: {RuntimeState.PLANNING, RuntimeState.HEALING, RuntimeState.FAILED},  # 路由后可进入计划、自愈或失败
    RuntimeState.PLANNING: {RuntimeState.EXECUTING, RuntimeState.HEALING, RuntimeState.FAILED},  # 计划后可进入执行、自愈或失败
    RuntimeState.EXECUTING: {RuntimeState.HEALING, RuntimeState.COMPLETED, RuntimeState.FAILED},  # 执行后可进入自愈、完成或失败
    RuntimeState.HEALING: {  # 自愈后可进入计划、执行、完成或失败
        RuntimeState.ROUTING,
        RuntimeState.PLANNING,
        RuntimeState.EXECUTING,
        RuntimeState.COMPLETED,
        RuntimeState.FAILED,
    },
    RuntimeState.COMPLETED: set(),  # 完成是终态，不能再转换
    RuntimeState.FAILED: set(),  # 失败是终态，不能再转换
}


class InvalidStateTransition(RuntimeError):
    """非法状态转换异常，当尝试进行不允许的状态转换时抛出"""
    pass


@dataclass(slots=True)
class RuntimeStateMachine:
    """
    运行时状态机
    
    管理编排运行时的状态转换，确保状态转换的合法性。
    维护当前状态和状态历史记录。
    
    属性:
        state: 当前状态
        _history: 状态历史记录
    """
    state: RuntimeState = RuntimeState.INITIALIZED  # 当前状态，初始为 INITIALIZED
    _history: list[RuntimeState] = field(default_factory=lambda: [RuntimeState.INITIALIZED])  # 状态历史

    def transition_to(self, next_state: RuntimeState) -> None:
        """
        转换到目标状态
        
        检查状态转换是否合法，如果合法则执行转换并记录历史。
        
        参数:
            next_state: 目标状态
            
        抛出:
            InvalidStateTransition: 当尝试非法状态转换时
        """
        allowed = _ALLOWED_TRANSITIONS[self.state]  # 获取允许的转换目标
        if next_state not in allowed:
            raise InvalidStateTransition(
                f"Illegal state transition: {self.state.value} -> {next_state.value}"
            )
        self.state = next_state  # 更新当前状态
        self._history.append(next_state)  # 记录状态历史

    @property
    def history(self) -> tuple[RuntimeState, ...]:
        """获取状态历史记录的不可变副本"""
        return tuple(self._history)
