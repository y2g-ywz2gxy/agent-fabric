# -*- coding: utf-8 -*-
"""
故障恢复模块

提供执行失败的分类和自愈处理功能：
- FailureClassifier: 故障分类器
- FailureType: 故障类型枚举
- SelfHealer: 自愈处理器
"""
from recovery.classifier import FailureClassifier, FailureType
from recovery.healer import SelfHealer

__all__ = ["FailureClassifier", "FailureType", "SelfHealer"]