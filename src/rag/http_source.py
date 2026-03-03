# -*- coding: utf-8 -*-
"""
HTTP 知识源模块

该模块提供了通过 HTTP 获取知识文档的功能，包括：
- SourceUnavailableError: 知识源不可用异常
- HTTPKnowledgeSource: HTTP 知识源实现
"""
from __future__ import annotations

import json
from typing import Any

import httpx


class SourceUnavailableError(RuntimeError):
    """知识源不可用异常，当 HTTP 请求失败时抛出"""
    pass


class HTTPKnowledgeSource:
    """
    HTTP 知识源
    
    通过 HTTP 请求获取知识文档，支持 JSON 和纯文本格式。
    提供关键字搜索功能用于文档检索。
    
    属性:
        _timeout_seconds: HTTP 请求超时时间
    """
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        """
        初始化 HTTP 知识源
        
        参数:
            timeout_seconds: 请求超时时间（秒）
        """
        self._timeout_seconds = timeout_seconds

    def fetch_documents(self, url: str) -> list[str]:
        """
        从指定 URL 获取文档
        
        发送 HTTP GET 请求获取文档内容，支持 JSON 和纯文本格式。
        
        参数:
            url: 文档 URL
            
        返回:
            文档内容列表
            
        抛出:
            SourceUnavailableError: 当请求失败时
        """
        try:
            response = httpx.get(url, timeout=self._timeout_seconds)
            response.raise_for_status()
        except Exception as exc:
            raise SourceUnavailableError(f"HTTP source unavailable: {exc}") from exc

        # 根据内容类型解析响应
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return self._extract_from_json(response.json())
        # 默认按行分割文本
        return [line.strip() for line in response.text.splitlines() if line.strip()]

    @staticmethod
    def keyword_search(query: str, documents: list[str], top_k: int = 5) -> list[dict[str, Any]]:
        """
        关键字搜索
        
        在文档列表中执行关键字搜索，返回最相关的文档。
        
        参数:
            query: 搜索查询
            documents: 文档列表
            top_k: 返回的最大文档数
            
        返回:
            包含 id、text、score 的搜索结果列表
        """
        # 分词并过滤空词
        words = [word for word in query.lower().split() if word]
        if not words:
            words = [query.lower()]

        # 计算每个文档的相关性得分
        scored: list[tuple[float, str]] = []
        for document in documents:
            text = document.lower()
            score = sum(text.count(word) for word in words)
            if score > 0:
                scored.append((float(score), document))

        # 按得分排序并返回 top_k
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"id": f"kw-{index}", "text": text, "score": score}
            for index, (score, text) in enumerate(scored[:top_k], start=1)
        ]

    @staticmethod
    def _extract_from_json(payload: Any) -> list[str]:
        """
        从 JSON 载荷提取文档
        
        支持多种 JSON 格式：
        - 列表格式
        - 包含 documents/items 字段的字典
        - 单个对象
        
        参数:
            payload: JSON 载荷
            
        返回:
            文档文本列表
        """
        # 列表格式：逐项提取
        if isinstance(payload, list):
            normalized: list[str] = []
            for item in payload:
                text = HTTPKnowledgeSource._to_text(item)
                if text:
                    normalized.append(text)
            return normalized
        # 字典格式：尝试提取 documents 或 items 字段
        if isinstance(payload, dict):
            docs = payload.get("documents") or payload.get("items") or []
            if isinstance(docs, list):
                normalized: list[str] = []
                for item in docs:
                    text = HTTPKnowledgeSource._to_text(item)
                    if text:
                        normalized.append(text)
                return normalized
            return [HTTPKnowledgeSource._to_text(payload)] if HTTPKnowledgeSource._to_text(payload) else []
        # 其他类型：转换为文本
        text = HTTPKnowledgeSource._to_text(payload)
        return [text] if text else []

    @staticmethod
    def _to_text(payload: Any) -> str:
        """
        将载荷转换为文本
        
        支持字符串、字典和其他类型的转换。
        
        参数:
            payload: 输入载荷
            
        返回:
            转换后的文本
        """
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            # 优先提取 text 字段
            if "text" in payload:
                return str(payload["text"]).strip()
            # 否则序列化为 JSON
            return json.dumps(payload, ensure_ascii=False)
        if payload is None:
            return ""
        return str(payload).strip()
