# CLAUDE.md — rag-api

Persist + hybrid search. **The only service that touches Postgres.**

## Invariants

1. **All tenant-scoped SQL runs inside `tenant_transaction()`** — a
   transaction with `app.tenant_id` set via `set_config(..., true)`. The
   RLS policies read it; outside it, tenant tables return zero rows.
2. **RLS uses FORCE** on every tenant-scoped table. Without FORCE the table
   owner (the role the app connects as) bypasses every policy silently.
   `tests/test_rls.py` asserts isolation, fail-closed, and cross-tenant
   write rejection — if those fail, multi-tenancy is decorative.
3. **Queries embed with `input_type="query"`**; documents were embedded
   with `"passage"` at ingest. Third service, same contract.
4. **`<#>` (inner product) ranks identically to cosine ONLY because every
   stored vector is unit-norm** — the embedder's norm-1.0 invariant is what
   makes `halfvec_ip_ops` correct.
5. **Idempotent persist**: one transaction per document, keyed on
   `(tenant_id, content_hash)`; re-posting is a no-op returning the
   existing id. A partially-persisted document is never visible.
6. **Migrations are plain SQL files** run in order at startup, tracked in
   `schema_migrations`. The schema is the documentation; keep decisions as
   SQL comments in the migration files.
7. `content_tsv` uses the `'simple'` config — no stemming, no stopwords.
   Stemming in the wrong language is worse than none (multilingual corpus).
8. **A "page" is `ceil(token_count / page_tokens)`, never the file
   format's own page numbers** — one huge single-page .txt must count as
   many pages or `max_pages_per_doc` means nothing. Quotas are enforced
   in `/internal/documents` (413 over-pages, 409 sandbox-full);
   `quota_exempt_tenants` (erb-v1, default) skip every cap.
9. **Billing tenant != retrieval tenant.** `/chat` retrieves from
   `x-tenant-slug` but budgets/records against `x-billing-tenant-slug`
   when present — the shared playground corpus answers while the asking
   user's own daily budget pays. Over budget: falls back to
   `LLM_FREE_MODEL` ($0 OpenRouter variant, SSE `model` event marks the
   turn) instead of 429ing; unset = hard 429.

## State

| | |
|---|---|
| implemented | migrations 0001–0007 (…RLS, usage_daily, analytics_events), persist endpoint with token-page quotas, hybrid search (bm25 default, `vector_weight=0.3`, tsquery fallback), rerank branch (window 50), `/chat` (SSE, grounding floor, model allowlist, daily budget + free fallback, billing split), `/internal/usage` + `/internal/events`, ERB bench harness (`bench/`, final 46.71 — `docs/SUBMISSION.md`, submitted for official review 2026-08-08, awaiting verdict; public claims stay framed as self-measured until it lands) |
| next | part 3 inventory: planning agent (the Azure-gap closer), reranker truncation/window ladder — chat rerank measured 16.5 s warm at window 50 (~330 ms/pair on the 2 vCPU reranker pod), which is why the UI ships rerank opt-in |

## Commands

```bash
uv sync
make run          # uvicorn on :8003
make test-db      # throwaway pgvector in docker + full integration tests
```

## Deployment

edka deployment (GitHub-repo mode, image tag strategy **Commit SHA** —
a floating :HEAD release record twice deployed fossils; if chat 404s
after an edka-side save, check the deployed tag first). ENVS (all owned
by edka's env panel, secrets in Secrets): `DATABASE_URL`, `EMBEDDER_URL`,
`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_PROVIDER` (OpenRouter),
`LLM_MODEL=anthropic/claude-haiku-4.5`, `LLM_MODELS` (dropdown roster),
`LLM_FREE_MODEL` (post-budget $0 fallback),
`CHAT_DAILY_TOKEN_BUDGET=50000`, `RERANKER_URL` (reranker lives in the
`default` namespace). rag-ingest posts to `/internal/documents`; rag-ui
is the only caller of `/chat` and `/internal/*` and derives billing
tenants from sessions.
