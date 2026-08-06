"""Reranker client. Degrades gracefully: a dead reranker must cost a
search request its quality boost, never its answer."""

from __future__ import annotations

import httpx


class RerankClient:
    def __init__(self, url: str, timeout_s: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"), timeout=timeout_s)

    async def order(self, query: str, texts: list[str]) -> list[int] | None:
        """Indices of texts sorted by relevance, or None on any failure."""
        try:
            response = await self._client.post(
                "/rerank", json={"query": query, "texts": texts})
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        return [r["index"] for r in response.json()["results"]]

    async def aclose(self) -> None:
        await self._client.aclose()
