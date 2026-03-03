# -*- coding: utf-8 -*-
"""
检索增强生成 (RAG) 模块

提供知识检索和文档获取功能：
- HTTPKnowledgeSource: HTTP 知识源
- HybridRetriever: 混合检索器
"""
from rag.http_source import HTTPKnowledgeSource, SourceUnavailableError
from rag.retriever import HybridRetriever, RetrievalBundle, SearchItem

__all__ = [
    "HTTPKnowledgeSource",
    "HybridRetriever",
    "RetrievalBundle",
    "SearchItem",
    "SourceUnavailableError",
]