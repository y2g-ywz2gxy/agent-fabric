from __future__ import annotations

from rag.retriever import HybridRetriever


def test_hybrid_retrieval_combines_keyword_and_vector_scores() -> None:
    def keyword_backend(query: str, top_k: int):
        return [
            {"id": "doc-a", "text": "alpha", "score": 0.6},
            {"id": "doc-b", "text": "beta", "score": 0.4},
        ]

    def vector_backend(query: str, top_k: int):
        return [
            {"id": "doc-b", "text": "beta", "score": 0.9},
            {"id": "doc-c", "text": "gamma", "score": 0.8},
        ]

    retriever = HybridRetriever(keyword_backend=keyword_backend, vector_backend=vector_backend)
    bundle = retriever.retrieve("query", top_k=3)

    ids = [item.id for item in bundle.items]
    assert not bundle.degraded
    assert ids[0] == "doc-b"
    assert set(ids) == {"doc-a", "doc-b", "doc-c"}


def test_hybrid_retrieval_falls_back_to_keyword_on_vector_failure() -> None:
    def keyword_backend(query: str, top_k: int):
        return [
            {"id": "doc-1", "text": "fallback-1", "score": 1.0},
            {"id": "doc-2", "text": "fallback-2", "score": 0.8},
        ]

    def broken_vector_backend(query: str, top_k: int):
        raise RuntimeError("vector service unavailable")

    retriever = HybridRetriever(
        keyword_backend=keyword_backend,
        vector_backend=broken_vector_backend,
    )
    bundle = retriever.retrieve("query", top_k=2)

    assert bundle.degraded
    assert bundle.reason is not None
    assert [item.id for item in bundle.items] == ["doc-1", "doc-2"]
