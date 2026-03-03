# -*- coding: utf-8 -*-
"""
可观测性指标收集模块

该模块提供了运行时指标的收集和统计功能，包括：
- MetricEvent: 指标事件数据类
- MetricsCollector: 指标收集器
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True, frozen=True)
class MetricEvent:
    """
    指标事件数据类
    
    记录单个指标事件的详细信息，包括事件名称、时间戳和标签。
    
    属性:
        name: 指标事件名称
        timestamp: 事件发生时间（UTC时间）
        tags: 事件的附加标签信息
    """
    name: str  # 指标事件名称
    timestamp: datetime  # 事件发生时间
    tags: dict[str, Any]  # 附加标签信息


class MetricsCollector:
    """
    指标收集器
    
    用于收集、存储和统计运行时指标事件。
    支持记录事件、按名称查询事件、统计事件计数等功能。
    """
    def __init__(self) -> None:
        """初始化指标收集器"""
        self._events: list[MetricEvent] = []  # 事件列表
        self._counters: Counter[str] = Counter()  # 计数器

    def record(self, name: str, **tags: Any) -> None:
        """
        记录一个指标事件
        
        参数:
            name: 指标事件名称
            **tags: 附加标签信息
        """
        self._events.append(
            MetricEvent(name=name, timestamp=datetime.now(timezone.utc), tags=tags)
        )
        self._counters[name] += 1  # 增加对应名称的计数

    def events(self, name: str | None = None) -> list[MetricEvent]:
        """
        获取事件列表
        
        参数:
            name: 可选的事件名称过滤器，如果为 None 则返回所有事件
            
        返回:
            匹配的事件列表
        """
        if name is None:
            return list(self._events)  # 返回所有事件的副本
        return [event for event in self._events if event.name == name]  # 按名称过滤

    def counter(self, name: str) -> int:
        """
        获取指定名称事件的计数
        
        参数:
            name: 事件名称
            
        返回:
            该名称事件的发生次数
        """
        return self._counters[name]
