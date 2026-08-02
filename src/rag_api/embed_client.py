"""Query-side embedder client. input_type="query" ALWAYS here -- documents
use "passage" at ingest. The asymmetric-prefix contract, third service."""

from __future__ import annotations

import httpx

INPUT_TYPE = "query"


class EmbedError(RuntimeError):
    pass


class QueryEmbedder:
    def __init__(self, url: str, timeout_s: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"), timeout=timeout_s)

    async def embed_query(self, text: str) -> list[float]:
        try:
            response = await self._client.post(
                "/embed", json={"texts": [text], "input_type": INPUT_TYPE})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbedError(f"embedder unreachable: {exc}") from exc
        return response.json()["embeddings"][0]

    async def healthy(self) -> bool:
        try:
            response = await self._client.get("/readyz")
            return response.status_code == 200
        except httpx.TransportError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
