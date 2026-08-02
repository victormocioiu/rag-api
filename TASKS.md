# TASKS — rag-api

Ordered. Each is independently verifiable.

## Session 3.1 — the schema and the two paths

- [x] Migrations: extensions (+ pgvector >= 0.8 gate), tenants,
      documents/chunks (halfvec 384, generated tsvector), HNSW ip + GIN,
      RLS with FORCE and fail-closed context
- [x] `db.py` — pool, boring SQL migration runner, `tenant_transaction()`
- [x] Persist: one transaction per document, idempotent on
      `(tenant_id, content_hash)`
- [x] Hybrid search: vector KNN + websearch full-text, RRF fusion,
      per-stage timings
- [x] Tests against real pgvector: migrations idempotent, persist
      round-trip, vector/lexical/hybrid, RLS isolation + fail-closed +
      cross-tenant write rejection

## Session 3.2 — wire and deploy

- [ ] rag-ingest: persist client (`RAG_API_URL`, optional like Valkey)
- [ ] Deploy via edka (stores pool first), smoke: ingest a doc end-to-end,
      search finds it
- [ ] Benchmark: persist latency per document, search p50 (embed_query vs
      db split), HNSW build time on a real backfill

## Session 3.3 — the eval harness (five registered ablations)

- [ ] Eval set with ground truth incl. table-questions
- [ ] Ablations: structural vs token; heading paths on/off; overlap;
      pdf_engine (pypdfium2 vs hybrid vs pymupdf); table_mode grid vs pairs
- [ ] Metrics: recall@k / MRR per ablation, cost-adjusted verdicts

## Session 3.4 — capstone

- [ ] EnterpriseRAG-Bench loader (their formats -> /ingest), full-corpus
      ingest on the cluster, one leaderboard-comparable score at the chosen
      config. Framing: performance-per-euro, set BEFORE the score exists

## Parts 4-5 (from the scaffold)

- [ ] Auth, tenants-for-real, quotas; chat (SSE), agent loop, providers
