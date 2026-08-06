"""rag-api: the only service that touches Postgres.

Persist (from rag-ingest, in-cluster) and search (hybrid: vector + lexical,
RRF-fused). Migrations run at startup -- boring, idempotent, visible SQL.

/readyz gates on the database (this service IS its database); the embedder
is a search-time dependency reported by /healthz and failed loudly per
request, never a readiness cascade.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response, StreamingResponse

from rag_api.config import get_settings
from rag_api.db import create_pool, ensure_tenant, resolve_tenant, run_migrations
from rag_api.embed_client import EmbedError, QueryEmbedder
from rag_api.llm import SYSTEM_PROMPT, AnswerLLM, LLMError, build_user_prompt
from rag_api.repositories import (
    persist_document,
    record_event,
    record_usage,
    search,
    tenant_usage,
    tokens_used_today,
)
from rag_api.rerank_client import RerankClient
from rag_api.schemas import (
    ChatRequest,
    ChatResponse,
    HitOut,
    PersistRequest,
    PersistResponse,
    SearchRequest,
    SearchResponse,
    SourceOut,
    TenantRequest,
)

state: dict[str, Any] = {}

PERSISTS = Counter("api_documents_persisted_total", "Documents persisted",
                   ["created"])
SEARCHES = Counter("api_searches_total", "Search requests", ["mode"])
CHATS = Counter("api_chats_total", "Chat requests")
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
    state["reranker"] = RerankClient(settings.reranker_url,
                                     settings.rerank_timeout_s)
    if settings.llm_api_key:
        state["llm"] = AnswerLLM(
            settings.llm_provider, settings.llm_api_key, settings.llm_model,
            base_url=settings.llm_base_url or None,
            max_tokens=settings.llm_max_tokens)
    yield
    await state["reranker"].aclose()
    if "llm" in state:
        await state["llm"].aclose()
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

    k_requested = request.k or settings.search_k
    t0 = time.perf_counter()
    hits = await search(
        state["pool"], tenant_id,
        query_embedding=query_embedding,
        query_text=request.query,
        k=settings.rerank_window if request.rerank else k_requested,
        mode=request.mode,
        candidates=settings.search_candidates,
        lexical_stopword_strip=request.lexical_stopword_strip,
        lexical_backend=request.lexical_backend,
        vector_weight=request.vector_weight,
    )
    timings["search"] = (time.perf_counter() - t0) * 1000
    if request.rerank:
        t0 = time.perf_counter()
        order = await state["reranker"].order(
            request.query, [h.content for h in hits])
        if order is not None:
            hits = [hits[i] for i in order]
        timings["rerank"] = (time.perf_counter() - t0) * 1000
        hits = hits[:k_requested]
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


async def _retrieve_for_chat(tenant_id: str, query: str, k: int,
                             rerank: bool = False,
                             ) -> tuple[list[SourceOut], dict[str, float]]:
    settings = get_settings()
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        query_embedding = await state["embedder"].embed_query(query)
    except EmbedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    timings["embed_query"] = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    hits = await search(
        state["pool"], tenant_id,
        query_embedding=query_embedding, query_text=query,
        k=settings.rerank_window if rerank else k,
        mode="hybrid", candidates=settings.search_candidates,
        lexical_backend=settings.chat_lexical_backend,
        vector_weight=settings.chat_vector_weight,
    )
    timings["search"] = (time.perf_counter() - t0) * 1000
    if rerank:
        t0 = time.perf_counter()
        order = await state["reranker"].order(query,
                                              [h.content for h in hits])
        if order is not None:
            hits = [hits[i] for i in order]
        timings["rerank"] = (time.perf_counter() - t0) * 1000
        hits = hits[:k]
    sources = [SourceOut(n=i, document_id=h.document_id,
                         heading_path=h.heading_path, content=h.content,
                         score=round(h.score, 6))
               for i, h in enumerate(hits, 1)]
    return sources, timings


@app.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    x_tenant_slug: str | None = Header(default=None),
):
    """Retrieval-augmented answer over the tenant's corpus. SSE stream by
    default (sources event, delta events, done event); stream=false for a
    plain ChatResponse. 503 when no LLM is configured -- search never
    depends on one."""
    if "llm" not in state:
        raise HTTPException(status_code=503, detail="no llm configured")
    settings = get_settings()
    tenant_id = await tenant_or_404(x_tenant_slug)

    model = request.model
    if model is not None:
        allowed = {m.strip() for m in settings.llm_models.split(",") if m.strip()}
        allowed.add(settings.llm_model)
        if model not in allowed:
            raise HTTPException(status_code=422, detail="model not allowed")

    if settings.chat_daily_token_budget:
        used = await tokens_used_today(state["pool"], tenant_id)
        if used >= settings.chat_daily_token_budget:
            raise HTTPException(status_code=429,
                                detail="daily token budget exhausted")

    k = request.k or settings.chat_chunks
    sources, timings = await _retrieve_for_chat(tenant_id, request.query, k,
                                                rerank=request.rerank)
    CHATS.inc()

    # grounding floor: nothing retrieved means nothing to answer from --
    # refuse server-side, spend zero LLM tokens, leave no jailbreak surface
    refusal = "I could not find that in the documents."
    if not sources:
        if not request.stream:
            return ChatResponse(answer=refusal, sources=[], timings_ms={
                k_: round(v, 1) for k_, v in timings.items()})

        async def refusal_events():
            yield "event: sources\ndata: []\n\n"
            yield ("event: delta\ndata: "
                   + json.dumps({"text": refusal}) + "\n\n")
            yield "event: done\ndata: {}\n\n"
        return StreamingResponse(refusal_events(),
                                 media_type="text/event-stream")

    prompt = build_user_prompt(
        request.query,
        [{"heading_path": s.heading_path, "content": s.content}
         for s in sources])
    tokens_in = (len(prompt) + len(SYSTEM_PROMPT)) // 4

    if not request.stream:
        t0 = time.perf_counter()
        try:
            parts = [d async for d in
                     state["llm"].stream(SYSTEM_PROMPT, prompt, model=model)]
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        timings["llm"] = (time.perf_counter() - t0) * 1000
        answer = "".join(parts)
        await record_usage(state["pool"], tenant_id, tokens_in,
                           len(answer) // 4)
        return ChatResponse(
            answer=answer, sources=sources,
            timings_ms={k_: round(v, 1) for k_, v in timings.items()})

    async def events():
        yield ("event: sources\ndata: "
               + json.dumps([s.model_dump() for s in sources]) + "\n\n")
        t0 = time.perf_counter()
        out_chars = 0
        try:
            async for delta in state["llm"].stream(SYSTEM_PROMPT, prompt,
                                                   model=model):
                out_chars += len(delta)
                yield ("event: delta\ndata: "
                       + json.dumps({"text": delta}) + "\n\n")
        except LLMError as exc:
            yield ("event: error\ndata: "
                   + json.dumps({"detail": str(exc)}) + "\n\n")
            return
        timings["llm"] = (time.perf_counter() - t0) * 1000
        await record_usage(state["pool"], tenant_id, tokens_in,
                           out_chars // 4)
        yield ("event: done\ndata: " + json.dumps(
            {"timings_ms": {k_: round(v, 1) for k_, v in timings.items()}})
            + "\n\n")

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/internal/usage")
async def usage_endpoint(
    x_tenant_slug: str | None = Header(default=None),
) -> dict:
    """Per-tenant quota picture for the UI's meters. Limits ride along so
    the client never hardcodes them."""
    settings = get_settings()
    tenant_id = await tenant_or_404(x_tenant_slug)
    usage = await tenant_usage(state["pool"], tenant_id)
    return {
        **usage,
        "limits": {
            "docs": 10,
            "pages_per_doc": 20,
            "tokens_per_day": settings.chat_daily_token_budget or None,
        },
    }


@app.post("/internal/events", status_code=204)
async def events_endpoint(rows: list[dict]) -> None:
    """First-party analytics sink; written by the UI's server routes only
    (internal network), one small batch per request."""
    for row in rows[:20]:
        await record_event(state["pool"], row)
