# -*- coding: utf-8 -*-
"""
执行结果数据结构模块

该模块定义了编排执行的结果类型，包括：
- ExecutionStatus: 执行状态枚举
- ExecutionResult: 执行结果数据类
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ExecutionStatus(str, Enum):
    """
    执行状态枚举
    
    定义了执行过程的两种最终状态。
    """
    SUCCESS = "success"  # 执行成功
    FAILED = "failed"  # 执行失败


@dataclass(slots=True, frozen=True)
class ExecutionResult:
    """
    执行结果数据类
    
    封装编排执行的返回结果，包含状态、数据、错误信息和下一步动作。
    使用 frozen=True 确保不可变性，slots=True 优化内存使用。
    
    属性:
        status: 执行状态（成功/失败）
        data: 返回的数据字典
        error: 错误信息（仅在失败时有值）
        next_action: 建议的下一步动作
    """
    status: ExecutionStatus  # 执行状态
    data: Mapping[str, Any] = field(default_factory=dict)  # 结果数据
    error: str | None = None  # 错误信息
    next_action: str | None = None  # 下一步动作

    @property
    def ok(self) -> bool:
        """检查执行是否成功"""
        return self.status is ExecutionStatus.SUCCESS

    @classmethod
    def success(
        cls,
        data: Mapping[str, Any] | None = None,
        *,
        next_action: str | None = None,
    ) -> "ExecutionResult":
        """
        创建成功的执行结果
        
        参数:
            data: 返回的数据
            next_action: 建议的下一步动作
            
        返回:
            成功状态的执行结果实例
        """
        return cls(
            status=ExecutionStatus.SUCCESS,
            data=data or {},
            next_action=next_action,
        )

    @classmethod
    def failure(
        cls,
        error: str,
        data: Mapping[str, Any] | None = None,
        *,
        next_action: str | None = None,
    ) -> "ExecutionResult":
        """
        创建失败的执行结果
        
        参数:
            error: 错误信息
            data: 返回的数据（可包含部分结果）
            next_action: 建议的下一步动作
            
        返回:
            失败状态的执行结果实例
        """
        return cls(
            status=ExecutionStatus.FAILED,
            data=data or {},
            error=error,
            next_action=next_action,
        )
