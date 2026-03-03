from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(slots=True, frozen=True)
class SearchItem:
    id: str
    text: str
    score: float
    channel: str


@dataclass(slots=True, frozen=True)
class RetrievalBundle:
    items: tuple[SearchItem, ...]
    degraded: bool
    reason: str | None = None


class HybridRetriever:
    def __init__(
        self,
        keyword_backend: Callable[[str, int], Iterable[Any]],
        vector_backend: Callable[[str, int], Iterable[Any]] | None = None,
    ) -> None:
        self._keyword_backend = keyword_backend
        self._vector_backend = vector_backend

    def retrieve(self, query: str, top_k: int = 5) -> RetrievalBundle:
        keyword_items = self._normalize(self._keyword_backend(query, top_k), channel="keyword")

        if self._vector_backend is None:
            ranked = tuple(sorted(keyword_items, key=lambda item: item.score, reverse=True)[:top_k])
            return RetrievalBundle(items=ranked, degraded=True, reason="vector_backend_not_configured")

        try:
            vector_items = self._normalize(self._vector_backend(query, top_k), channel="vector")
        except Exception as exc:
            ranked = tuple(sorted(keyword_items, key=lambda item: item.score, reverse=True)[:top_k])
            return RetrievalBundle(items=ranked, degraded=True, reason=f"vector_failed:{exc}")

        merged: dict[str, SearchItem] = {}
        for item in keyword_items:
            key = item.id or item.text
            merged[key] = SearchItem(item.id, item.text, item.score * 0.4, item.channel)

        for item in vector_items:
            key = item.id or item.text
            previous = merged.get(key)
            vector_weighted = item.score * 0.6
            if previous is None:
                merged[key] = SearchItem(item.id, item.text, vector_weighted, item.channel)
            else:
                merged[key] = SearchItem(
                    id=item.id,
                    text=item.text,
                    score=previous.score + vector_weighted,
                    channel="hybrid",
                )

        ranked = tuple(sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k])
        return RetrievalBundle(items=ranked, degraded=False)

    @staticmethod
    def _normalize(items: Iterable[Any], *, channel: str) -> list[SearchItem]:
        normalized: list[SearchItem] = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, SearchItem):
                normalized.append(item)
                continue

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

            normalized.append(
                SearchItem(
                    id=f"{channel}-{index}",
                    text=str(item),
                    score=1.0,
                    channel=channel,
                )
            )
        return normalized
