# -*- coding: utf-8 -*-
"""
混合检索器模块

该模块提供了关键字和向量混合检索功能，包括：
- SearchItem: 检索结果项数据类
- RetrievalBundle: 检索结果集数据类
- HybridRetriever: 混合检索器
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(slots=True, frozen=True)
class SearchItem:
    """
    检索结果项数据类
    
    表示单个检索结果，包含文档标识、文本、得分和来源渠道。
    
    属性:
        id: 文档标识符
        text: 文档文本内容
        score: 相关性得分
        channel: 来源渠道（keyword/vector/hybrid）
    """
    id: str  # 文档 ID
    text: str  # 文档文本
    score: float  # 相关性得分
    channel: str  # 来源渠道


@dataclass(slots=True, frozen=True)
class RetrievalBundle:
    """
    检索结果集数据类
    
    封装检索结果，包含结果项列表和降级状态。
    
    属性:
        items: 检索结果项元组
        degraded: 是否处于降级状态
        reason: 降级原因（如果有）
    """
    items: tuple[SearchItem, ...]  # 检索结果项
    degraded: bool  # 是否降级
    reason: str | None = None  # 降级原因


class HybridRetriever:
    """
    混合检索器
    
    结合关键字检索和向量检索，提供更准确的检索结果。
    支持降级到纯关键字检索（当向量后端不可用时）。
    
    属性:
        _keyword_backend: 关键字检索后端函数
        _vector_backend: 向量检索后端函数（可选）
    """
    def __init__(
        self,
        keyword_backend: Callable[[str, int], Iterable[Any]],
        vector_backend: Callable[[str, int], Iterable[Any]] | None = None,
    ) -> None:
        """
        初始化混合检索器
        
        参数:
            keyword_backend: 关键字检索后端函数，接收查询和 top_k 参数
            vector_backend: 向量检索后端函数（可选）
        """
        self._keyword_backend = keyword_backend
        self._vector_backend = vector_backend

    def retrieve(self, query: str, top_k: int = 5) -> RetrievalBundle:
        """
        执行混合检索
        
        结合关键字和向量检索结果，按权重合并排序。
        权重分配：关键字 0.4，向量 0.6。
        
        参数:
            query: 检索查询
            top_k: 返回的最大结果数
            
        返回:
            检索结果集
        """
        # 执行关键字检索
        keyword_items = self._normalize(self._keyword_backend(query, top_k), channel="keyword")

        # 如果没有向量后端，只使用关键字检索
        if self._vector_backend is None:
            ranked = tuple(sorted(keyword_items, key=lambda item: item.score, reverse=True)[:top_k])
            return RetrievalBundle(items=ranked, degraded=True, reason="vector_backend_not_configured")

        # 尝试执行向量检索
        try:
            vector_items = self._normalize(self._vector_backend(query, top_k), channel="vector")
        except Exception as exc:
            # 向量检索失败，降级到纯关键字
            ranked = tuple(sorted(keyword_items, key=lambda item: item.score, reverse=True)[:top_k])
            return RetrievalBundle(items=ranked, degraded=True, reason=f"vector_failed:{exc}")

        # 合并关键字和向量结果
        merged: dict[str, SearchItem] = {}
        # 添加关键字结果，权重 0.4
        for item in keyword_items:
            key = item.id or item.text
            merged[key] = SearchItem(item.id, item.text, item.score * 0.4, item.channel)

        # 合并向量结果，权重 0.6
        for item in vector_items:
            key = item.id or item.text
            previous = merged.get(key)
            vector_weighted = item.score * 0.6
            if previous is None:
                # 新结果
                merged[key] = SearchItem(item.id, item.text, vector_weighted, item.channel)
            else:
                # 合并得分，标记为混合来源
                merged[key] = SearchItem(
                    id=item.id,
                    text=item.text,
                    score=previous.score + vector_weighted,
                    channel="hybrid",
                )

        # 按得分排序返回 top_k
        ranked = tuple(sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k])
        return RetrievalBundle(items=ranked, degraded=False)

    @staticmethod
    def _normalize(items: Iterable[Any], *, channel: str) -> list[SearchItem]:
        """
        规范化检索结果
        
        将不同格式的检索结果统一转换为 SearchItem 列表。
        支持的格式：SearchItem、dict、其他类型。
        
        参数:
            items: 原始检索结果
            channel: 来源渠道
            
        返回:
            规范化的 SearchItem 列表
        """
        normalized: list[SearchItem] = []
        for index, item in enumerate(items, start=1):
            # 已经是 SearchItem 类型
            if isinstance(item, SearchItem):
                normalized.append(item)
                continue

            # 字典类型
            if isinstance(item, dict):
                normalized.append(
                    SearchItem(
                        id=str(item.get("id") or f"{channel}-{index}"),
                        text=str(item.get("text") or ""),
                        score=float(item.get("score") or 0.0),
                        channel=str(item.get("channel") or channel),
                    )
                )
                continue

            # 其他类型：转换为字符串
            normalized.append(
                SearchItem(
                    id=f"{channel}-{index}",
                    text=str(item),
                    score=1.0,
                    channel=channel,
                )
            )
        return normalized
