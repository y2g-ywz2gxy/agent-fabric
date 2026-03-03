from __future__ import annotations

import json
from typing import Any

import httpx


class SourceUnavailableError(RuntimeError):
    pass


class HTTPKnowledgeSource:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch_documents(self, url: str) -> list[str]:
        try:
            response = httpx.get(url, timeout=self._timeout_seconds)
            response.raise_for_status()
        except Exception as exc:
            raise SourceUnavailableError(f"HTTP source unavailable: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return self._extract_from_json(response.json())
        return [line.strip() for line in response.text.splitlines() if line.strip()]

    @staticmethod
    def keyword_search(query: str, documents: list[str], top_k: int = 5) -> list[dict[str, Any]]:
        words = [word for word in query.lower().split() if word]
        if not words:
            words = [query.lower()]

        scored: list[tuple[float, str]] = []
        for document in documents:
            text = document.lower()
            score = sum(text.count(word) for word in words)
            if score > 0:
                scored.append((float(score), document))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"id": f"kw-{index}", "text": text, "score": score}
            for index, (score, text) in enumerate(scored[:top_k], start=1)
        ]

    @staticmethod
    def _extract_from_json(payload: Any) -> list[str]:
        if isinstance(payload, list):
            normalized: list[str] = []
            for item in payload:
                text = HTTPKnowledgeSource._to_text(item)
                if text:
                    normalized.append(text)
            return normalized
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
        text = HTTPKnowledgeSource._to_text(payload)
        return [text] if text else []

    @staticmethod
    def _to_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if isinstance(payload, dict):
            if "text" in payload:
                return str(payload["text"]).strip()
            return json.dumps(payload, ensure_ascii=False)
        if payload is None:
            return ""
        return str(payload).strip()
