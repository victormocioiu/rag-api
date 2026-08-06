# Session 4.3 — the reranker: measure, build, confirm

2026-08-06. Three acts in 24 hours, in the platform's canonical order:
prototype offline, build only what measured well, confirm at full scale.

## Act 1 — the $1 prototype (before any service existed)

Candidates dumped straight from Postgres (bm25 top-150 + vector top-150
per question), cross-encoder (bge-reranker-v2-m3) run on a laptop GPU,
judged on the 100-q slice:

- recall@10: +2.8 only — capped by the candidate pool (gold absent for
  most semantic questions; no reordering fixes what retrieval never
  fetched). A partial-run mirage (+10 at n=36) died at n=100, again.
- score blending: pure CE beat every CE+RRF mix tried. Intra-doc
  questions lose (-37 r@1 on the slice): independent chunk scoring
  scatters a single document's sections. Known, accepted, agent-loop
  territory later.
- **the number that justified the build: answers from reranked top-8
  scored OVERALL 41.39 vs 37.32** — the reranker's product is SELECTION
  quality, not recall. The k16 lesson's positive mirror: selection beats
  width, proven in both directions.

## Act 2 — rag-reranker, the fourth service

rag-embedder's recipe verbatim: model exported + int8-quantized
(avx512_vnni, per-channel) on GitHub runners into a ghcr model image
(the export needs the embedder's exact pins -- torch <2.9 for the
legacy exporter; the comment in its pyproject paid for itself), app
image FROM it, edka deploy, port 8004. Token-budget batching is
invariant #1 at birth. /rerank: (query, texts[]) -> ranked indices.

Measured on the serving pod (2 vCPU, sharing the embed node):
~175ms/pair at 480 tokens -- 9s per 50-pair window warm, 18s cold.
Quality mode only until a size/truncation ladder buys latency back;
`rerank: bool` defaults false on /search and /chat, and a dead reranker
degrades to un-reranked results rather than failing the request.

Deploy gremlins, for the honesty ledger: the service landed in the
`default` namespace (RERANKER_URL env now points there), and edka's
image tracking flipped to a floating `:HEAD` tag that resolved stale --
"everything green, behavior from three commits ago" joins the failure
signature collection.

## Act 3 — the full-500 confirmation

| | no rerank (4.2b) | **reranked** |
|---|---|---|
| Correctness | 42.8 | **46.4** |
| Completeness | 48.9 | **52.8** |
| **Overall** | 38.22 | **42.11** |
| Document Recall | 66.37 | **69.68** |
| Invalid extras | 9.02 | 8.99 |

The slice predicted +4.1; the full set delivered +3.9. **Overall now
7th of 14** (past Vertex 41.87, margin inside judge noise -- call it a
statistical tie), recall 0.7 behind Amazon Kendra's 5th. Cost of the
confirmation: ~$4.65.

Per category: basic 47.5 -> 52.4 combined, semantic 18.7 -> 27.4 (the
reranker rescues borderline retrievals), intra-doc holds despite the
slice's warning (95.0 recall). project_related regressed (15.0 correct)
-- multi-doc questions remain structurally unsolved by anything that
scores chunks independently. That, and semantic's remaining gap, are
the multi-query and agent-loop sessions' inheritance.

The climb: 32.44 -> 38.22 (model ladder) -> 42.11 (reranker).
Target: above Azure (48.42) and Amazon Q (48.96).
