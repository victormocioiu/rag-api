# rag-api

Persist and search — the memory of the pipeline, and the only service that
touches Postgres.

```
rag-ingest ──POST /internal/documents──▶ rag-api ──▶ Postgres (halfvec + tsvector + RLS)
   client  ──POST /search──────────────▶ rag-api ──▶ hybrid: vector KNN + full-text, RRF-fused
```

## Why one database does hybrid search

The `chunks` table carries both halves: `embedding halfvec(384)` under an
HNSW index (`halfvec_ip_ops` — inner product equals cosine because the
embedder L2-normalizes), and `content_tsv`, a generated tsvector under a GIN
index that Postgres maintains itself. One table, two indexes, no
Elasticsearch. Results fuse with reciprocal-rank fusion.

## Multi-tenancy that isn't decorative

Every tenant-scoped table has row-level security with **FORCE** — the word
that makes policies apply to the table owner too. The tenant context is set
per transaction (`SET LOCAL`), and an unset context yields zero rows:
fail-closed. `tests/test_rls.py` proves isolation, fail-closed reads, and
cross-tenant write rejection against a real Postgres.

## API

| | |
|---|---|
| `POST /internal/documents` | idempotent persist from rag-ingest (one transaction per document) |
| `POST /search` | `{query, k?, mode: hybrid\|vector\|lexical}`; per-stage timings in the response |
| `GET /healthz` `/readyz` `/metrics` | the usual trio; readiness gates on the database |

## Local

```bash
uv sync
make test-db     # docker pgvector + the full integration suite
make run         # :8003 (needs DATABASE_URL and a reachable embedder)
```

Migrations are plain SQL in `migrations/`, applied in order at startup,
tracked in `schema_migrations`. Read them — the schema is the documentation.
