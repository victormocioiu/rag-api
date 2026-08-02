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

## State

| | |
|---|---|
| implemented | migrations (extensions/tenants/documents/chunks/indexes/RLS), persist endpoint, hybrid search (vector + lexical, RRF), query embedder client |
| next | eval harness (5 registered ablations), EnterpriseRAG-Bench capstone, chat/auth (parts 4-5) |

## Commands

```bash
uv sync
make run          # uvicorn on :8003
make test-db      # throwaway pgvector in docker + full integration tests
```

## Deployment

edka deployment (GitHub-repo mode). ENVS: `DATABASE_URL` (CNPG app secret,
`rag-pg-rw.postgres.svc` host), `EMBEDDER_URL`. Placement: stores pool puts
search next to Postgres; measure before moving it. rag-ingest posts to
`/internal/documents` (set `RAG_API_URL` on rag-ingest).
