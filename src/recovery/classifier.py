# -*- coding: utf-8 -*-
"""
故障分类器模块

该模块提供了执行失败的分类功能，包括：
- FailureType: 故障类型枚举
- FailureClassifier: 故障分类器
"""
from __future__ import annotations

from enum import Enum

from orchestrator.result import ExecutionResult


class FailureType(str, Enum):
    """
    故障类型枚举
    
    定义了可能的执行失败类型：
    - TIMEOUT: 超时错误
    - TOOL_ERROR: 工具错误
    - DEPENDENCY_FAILURE: 依赖服务故障
    - EMPTY_RETRIEVAL: 检索结果为空
    - PLANNING_FAILURE: 计划失败
    - UNKNOWN: 未知错误
    """
    TIMEOUT = "timeout"  # 超时错误
    TOOL_ERROR = "tool_error"  # 工具错误
    DEPENDENCY_FAILURE = "dependency_failure"  # 依赖服务故障
    EMPTY_RETRIEVAL = "empty_retrieval"  # 检索结果为空
    PLANNING_FAILURE = "planning_failure"  # 计划失败
    UNKNOWN = "unknown"  # 未知错误


class FailureClassifier:
    """
    故障分类器
    
    根据错误信息中的关键字对执行失败进行分类。
    支持中英文关键字的识别。
    """
    def classify(self, result: ExecutionResult) -> FailureType:
        """
        分类执行失败
        
        根据错误信息中的关键字判断失败类型。
        
        参数:
            result: 执行结果
            
        返回:
            失败类型枚举值
        """
        error = (result.error or "").lower()

        # 超时错误检测
        if "timeout" in error or "超时" in error:
            return FailureType.TIMEOUT
        # 工具错误检测
        if "tool" in error or "工具" in error:
            return FailureType.TOOL_ERROR
        # 依赖服务故障检测
        if "dependency" in error or "依赖" in error:
            return FailureType.DEPENDENCY_FAILURE
        # 空检索检测
        if "empty retrieval" in error or "空检索" in error:
            return FailureType.EMPTY_RETRIEVAL
        # 计划失败检测
        if "planning" in error or "plan" in error or result.next_action == "replan":
            return FailureType.PLANNING_FAILURE

        # 未知错误
        return FailureType.UNKNOWN
