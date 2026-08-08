# EnterpriseRAG-Bench submission — hRAG

**Status: SUBMITTED 2026-08-08** — emailed to the maintainers with the
answers file, this writeup, and the raw harness output; awaiting
official review. Until their verdict lands, every number below is our
self-measured claim (their harness, our run), and the public site says
exactly that.

**System**: hRAG — self-hosted hybrid RAG on a €116/month Hetzner
Kubernetes cluster. Postgres-only storage (pgvector + pg_textsearch
BM25), multilingual-e5-small int8 embeddings, cross-encoder reranking
(bge-reranker-v2-m3 int8), claude-sonnet-5 answering over the top-12
reranked chunks. Fully open source across five repos.

**Self-measured results** (all 500 questions, answers file included):

| metric | score |
|---|---|
| Overall (correctness x completeness) | 46.71 |
| Answer Correctness | 53.0 |
| Answer Completeness | 56.5 |
| Document Recall | 69.6 |
| Invalid Extra Docs | 9.0 |

**Judging transparency**: our runs were scored with the benchmark's own
`metrics_based_eval` harness, driven by `gpt-5.6-luna` via OpenRouter's
OpenAI-compatible endpoint (`OPENAI_BASE_URL` + `LLM_MODEL_NAME`)
instead of the default gpt-5.4 judge, for cost. We measured the judge
delta directly: the same 100-question answer set scored 37.69 under
gpt-5.4 and 37.32 under luna (delta 0.37, luna slightly stricter). An
earlier full-500 run at a weaker config was fully gpt-5.4-judged
(docs/benchmarks-4.1.md) and its recall matched our set-math to 0.13
points. We expect official re-judging and welcome it.

## Reproduce

1. Platform: five repos (rag-embedder, rag-ingest, rag-api,
   rag-reranker, rag-ui under github.com/victormocioiu), each with a
   CLAUDE.md and deployment notes; the benchmark corpus is ingested
   through the public /ingest path (bench/ingest_bench.py -- resumable,
   ~12h at ~30k tokens/s on a temporary 16-vCPU node).
2. Answers: `bench/answer_bench.py --rerank --chunks 12` with
   `LLM_MODEL=anthropic/claude-sonnet-5` (retrieval through the live
   /search API: hybrid, bm25 arm, vector weight 0.3, rerank window 50).
   Submission artifact: `bench/answers-submission-final.jsonl`.
3. Scoring: their harness, command in docs/benchmarks-4.1.md.
4. The full measurement history, including six negative results, lives
   in docs/benchmarks-*.md.

Contact: Victor Mocioiu — victormocioiu@gmail.com
