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

- [x] rag-ingest: persist client (`RAG_API_URL`, optional like Valkey)
- [x] Deploy via edka (stores pool), smoke: full circle verified (77-days
      query answered; idempotency across postgres+valkey proven)
- [x] Benchmark: 2,000-doc seed through the real pipeline; HNSW flat
      (3ms at 20K chunks), persist ~2.5ms/chunk, batch-token fix
      (EMBED_BATCH_SIZE=8) — `docs/benchmarks-3.2.md`

## Session 3.3 — the eval harness (six registered ablations)

- [x] Eval set with ground truth incl. table-questions (planted markers,
      42 docs, 104 queries across 6 classes — `eval/build_corpus.py`)
- [x] Ablations: structural vs token; heading paths on/off; overlap;
      pdf_engine (pypdf vs pypdfium2 vs hybrid); table_mode grid vs pairs;
      query-side stopword strip (tenant-per-ablation via RLS)
- [x] Metrics: recall@k / MRR per ablation + per query class, cost-adjusted
      verdicts — `docs/benchmarks-3.3.md`, `results/eval-amd-v1.json`.
      Winner: hybrid + strip (MRR 0.933); heading paths most load-bearing
      knob; cross-lingual e5-small 1/8 (honest negative)

## Session 3.4 — capstone

- [ ] EnterpriseRAG-Bench loader (their formats -> /ingest), full-corpus
      ingest on the cluster, one leaderboard-comparable score at the chosen
      config. Framing: performance-per-euro, set BEFORE the score exists

## Parts 4-5 (from the scaffold)

- [ ] Auth, tenants-for-real, quotas; chat (SSE), agent loop, providers
