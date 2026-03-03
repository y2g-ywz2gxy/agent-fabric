# -*- coding: utf-8 -*-
"""
自愈处理器模块

该模块提供了执行失败后的自愈处理功能，根据故障类型
决定恢复策略。
"""
from __future__ import annotations

from orchestrator.interfaces import Healer, OrchestrationContext
from orchestrator.result import ExecutionResult
from recovery.classifier import FailureClassifier, FailureType


class SelfHealer(Healer):
    """
    自愈处理器
    
    根据故障类型提供恢复策略：
    - TIMEOUT/TOOL_ERROR/DEPENDENCY_FAILURE: 重试执行
    - PLANNING_FAILURE: 重新计划
    - EMPTY_RETRIEVAL: 重新计划
    
    属性:
        _classifier: 故障分类器
        _max_rounds: 最大自愈轮次
    """
    def __init__(self, classifier: FailureClassifier, max_rounds: int = 2) -> None:
        """
        初始化自愈处理器
        
        参数:
            classifier: 故障分类器实例
            max_rounds: 最大自愈轮次
        """
        self._classifier = classifier
        self._max_rounds = max(1, max_rounds)

    def heal(
        self,
        failed_result: ExecutionResult,
        context: OrchestrationContext,
        *,
        attempt: int,
    ) -> ExecutionResult:
        """
        执行自愈处理
        
        根据失败类型决定恢复策略。
        
        参数:
            failed_result: 失败的执行结果
            context: 编排上下文
            attempt: 当前尝试次数
            
        返回:
            包含恢复策略的执行结果
        """
        # 检查是否超过最大自愈轮次
        if attempt >= self._max_rounds:
            return ExecutionResult.failure(
                "Healing failed: exceeded max healing rounds.",
                {
                    "attempt": attempt,
                    "query": context.query,
                },
                next_action="abort",
            )

        # 对失败进行分类
        failure_type = self._classifier.classify(failed_result)

        # 可重试的错误类型
        if failure_type in {FailureType.TIMEOUT, FailureType.TOOL_ERROR, FailureType.DEPENDENCY_FAILURE}:
            return ExecutionResult.success(
                {
                    "attempt": attempt,
                    "failure_type": failure_type.value,
                },
                next_action="retry_execute",
            )

        # 计划失败需要重新计划
        if failure_type is FailureType.PLANNING_FAILURE:
            return ExecutionResult.success(
                {
                    "attempt": attempt,
                    "failure_type": failure_type.value,
                },
                next_action="replan",
            )

        # 空检索需要重新计划
        if failure_type is FailureType.EMPTY_RETRIEVAL:
            return ExecutionResult.success(
                {
                    "attempt": attempt,
                    "failure_type": failure_type.value,
                },
                next_action="replan",
            )

        # 未知错误类型，无法自愈
        return ExecutionResult.failure(
            f"Healing failed: no strategy for {failure_type.value}.",
            {
                "attempt": attempt,
                "failure_type": failure_type.value,
            },
            next_action="abort",
        )
