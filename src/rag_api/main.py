"""rag-api: the only service that touches Postgres.

Persist (from rag-ingest, in-cluster) and search (hybrid: vector + lexical,
RRF-fused). Migrations run at startup -- boring, idempotent, visible SQL.

/readyz gates on the database (this service IS its database); the embedder
is a search-time dependency reported by /healthz and failed loudly per
request, never a readiness cascade.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from rag_api.config import get_settings
from rag_api.db import create_pool, ensure_tenant, resolve_tenant, run_migrations
from rag_api.embed_client import EmbedError, QueryEmbedder
from rag_api.repositories import persist_document, search
from rag_api.schemas import (
    HitOut,
    PersistRequest,
    PersistResponse,
    SearchRequest,
    SearchResponse,
    TenantRequest,
)

state: dict[str, Any] = {}

PERSISTS = Counter("api_documents_persisted_total", "Documents persisted",
                   ["created"])
SEARCHES = Counter("api_searches_total", "Search requests", ["mode"])
STAGE = Histogram("api_stage_seconds", "Stage latency", ["stage"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = await create_pool(settings.database_url)
    applied = await run_migrations(pool)
    if applied:
        print(f"migrations applied: {applied}", flush=True)
    state["pool"] = pool
    state["embedder"] = QueryEmbedder(settings.embedder_url,
                                      settings.embed_timeout_s)
    yield
    await state["embedder"].aclose()
    await pool.close()
    state.clear()


app = FastAPI(title="rag-api", lifespan=lifespan)


async def tenant_or_404(slug: str | None) -> str:
    settings = get_settings()
    tenant_id = await resolve_tenant(
        state["pool"], slug or settings.default_tenant_slug)
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="unknown tenant")
    return tenant_id


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    pool = state.get("pool")
    embedder = state.get("embedder")
    db_ok = False
    if pool is not None:
        try:
            db_ok = await pool.fetchval("SELECT 1") == 1
        except Exception:  # noqa: BLE001 -- health endpoint reports, never raises
            db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "embedder_reachable": await embedder.healthy() if embedder else False,
    }


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    pool = state.get("pool")
    if pool is None:
        raise HTTPException(status_code=503, detail="no database pool")
    try:
        await pool.fetchval("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unreachable") from exc
    return {"status": "ready"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/internal/tenants")
async def create_tenant(request: TenantRequest) -> dict:
    tenant_id = await ensure_tenant(
        state["pool"], request.slug, request.name or request.slug)
    return {"tenant_id": tenant_id, "slug": request.slug}


@app.post("/internal/documents", response_model=PersistResponse)
async def persist(
    request: PersistRequest,
    x_tenant_slug: str | None = Header(default=None),
) -> PersistResponse:
    tenant_id = await tenant_or_404(x_tenant_slug)
    if not request.chunks:
        raise HTTPException(status_code=422, detail="no chunks")
    started = time.perf_counter()
    result = await persist_document(
        state["pool"], tenant_id,
        content_hash_hex=request.content_hash,
        filename=request.filename,
        mime_type=request.mime_type,
        byte_size=request.byte_size,
        chunks=[c.model_dump() for c in request.chunks],
    )
    STAGE.labels("persist").observe(time.perf_counter() - started)
    PERSISTS.labels(str(result.created).lower()).inc()
    return PersistResponse(document_id=result.document_id,
                           created=result.created, n_chunks=result.n_chunks)


@app.post("/search", response_model=SearchResponse)
async def search_endpoint(
    request: SearchRequest,
    x_tenant_slug: str | None = Header(default=None),
) -> SearchResponse:
    settings = get_settings()
    tenant_id = await tenant_or_404(x_tenant_slug)
    if request.mode not in ("hybrid", "vector", "lexical"):
        raise HTTPException(status_code=422, detail="bad mode")
    if request.lexical_backend not in ("tsquery", "bm25"):
        raise HTTPException(status_code=422, detail="bad lexical_backend")
    timings: dict[str, float] = {}

    query_embedding = None
    if request.mode in ("hybrid", "vector"):
        t0 = time.perf_counter()
        try:
            query_embedding = await state["embedder"].embed_query(request.query)
        except EmbedError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        timings["embed_query"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    hits = await search(
        state["pool"], tenant_id,
        query_embedding=query_embedding,
        query_text=request.query,
        k=request.k or settings.search_k,
        mode=request.mode,
        candidates=settings.search_candidates,
        lexical_stopword_strip=request.lexical_stopword_strip,
        lexical_backend=request.lexical_backend,
    )
    timings["search"] = (time.perf_counter() - t0) * 1000
    SEARCHES.labels(request.mode).inc()
    for stage, ms in timings.items():
        STAGE.labels(stage).observe(ms / 1000)

    return SearchResponse(
        query=request.query, mode=request.mode,
        timings_ms={k: round(v, 1) for k, v in timings.items()},
        hits=[HitOut(
            chunk_id=h.chunk_id, document_id=h.document_id, ordinal=h.ordinal,
            heading_path=h.heading_path, page=h.page, score=round(h.score, 6),
            vector_rank=h.vector_rank, lexical_rank=h.lexical_rank,
            content=h.content,
        ) for h in hits],
    )
