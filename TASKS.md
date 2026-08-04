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

- [x] EnterpriseRAG-Bench loader (their formats -> /ingest), full-corpus
      ingest on the cluster (511,926 docs / 1.59M chunks / 590M tokens,
      ~13h on a €0.104/h CPX62 burst pool), one leaderboard-comparable
      score at the chosen config. Framing: performance-per-euro, set
      BEFORE the score existed. Score: Document Recall 0.219 — prediction
      (0.5-0.7) wrong in public; diagnosis in `docs/benchmarks-3.4.md`
      (384-dim crowding: gold chunk at vector rank 15,698 of 1.6M;
      lexical AND-death at question length; lexical latency wall 10.6s
      p50 vs vector 139ms). Four production bugs found and fixed along
      the way. Retrieval upgrades = part 4-5 backlog, measurable against
      this harness

## Session 3.5 — real BM25 in Postgres

- [x] pg_textsearch 1.3.1 on the live cluster via CNPG declarative
      image-volume extensions (zot-hosted 874KB image, two rolling
      restarts, zero data loss); bm25 index on 1.59M chunks (~10 min)
- [x] rag-api: `lexical_backend=bm25` arm + `vector_weight` fusion knob;
      migration 0005 no-ops without the extension (tsquery stays default)
- [x] Re-scored: hybrid w=0.3 **0.662** (was 0.219); bm25 solo 0.654 at
      207ms vs 10.6s; paper's winning baseline 0.684 — gap 0.022.
      `docs/benchmarks-3.5.md`

## Part 2 (approved order; demo product: public domain via edka,
## shared ERB playground tenant, per-user sandboxes 10 docs / 20 pages)

- [x] 1. Generation layer: POST /chat -- retrieval (chat defaults = ERB
      winners: bm25 + w0.3) -> provider-agnostic AnswerLLM (openai-compat
      + anthropic, raw REST SSE) -> streamed answer with numbered [n]
      citations; 503 without a key (search never depends on an LLM);
      FakeLLM contract tests
- [x] 1a. Guardrails + metering: grounding floor (empty retrieval ->
      server-side refusal, zero LLM tokens), injection-resistant system
      prompt (context is DATA not instructions), per-request model with
      allowlist (OpenRouter-ready via LLM_BASE_URL), usage_daily table
      (RLS'd) + CHAT_DAILY_TOKEN_BUDGET -> 429
- [ ] 1b. ERB official run: batch answer generation over
      answers-erb-final questions -> their metrics_based_eval (needs
      LLM_API_KEY + judge budget) -> leaderboard submission w/ repro guide
- [ ] 2. Reranker service (ceiling 64% within top-200; re-measure over
      FUSED candidates first); fixes ~9 invalid-extras
- [ ] 3. Auth + tenants-for-real: UI with Auth.js (Google + GitLab),
      API keys, quotas (10 docs / 20 pages/doc), public domain, shared
      read-only ERB tenant
- [ ] 4. Retrieval experiments (harness ready): query rewriting,
      embedder sweep offline, english-stemming bm25 index
- [ ] 5. Platform debt: bm25 + w0.3 as defaults, ingest keep-alive skew,
      20-doc parser edge, S3 originals, GET /documents
