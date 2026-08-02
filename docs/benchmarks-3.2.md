# Session 3.2 — persist and search, measured

2026-08-02. 2,000 synthetic documents (mixed sizes: 1/4/10 sections) seeded
through the REAL pipeline — rag-ingest → rag-embedder → rag-api → Postgres —
from an in-cluster client, pausing at corpus checkpoints to measure search.
19,990 chunks in 1,108s end-to-end (~18 chunks/s including persistence,
consistent with the embedder-bound token rate from part 2).

## Search vs corpus size

![scaling](figures/search_scaling.png)

| corpus | vector (db) | lexical (db) | hybrid (db) | embed query |
|---|---|---|---|---|
| 1K chunks | 2.7ms | 4.0ms | 6.8ms | ~18ms |
| 5K | 2.4ms | 18.4ms | 20.5ms | ~17ms |
| 10K | 2.5ms | 33.9ms | 35.5ms | ~18ms |
| 20K | **3.2ms** | 71.5ms | 75.7ms | ~20ms |

1. **HNSW is flat**: 2.7 → 3.2ms across a 20× corpus growth. That is the
   entire argument for approximate nearest-neighbor indexes, measured.
2. **The lexical line is a worst-case artifact — and a real lesson.** The
   synthetic corpus recycles 20 words, so every query term matches nearly
   every chunk and `ts_rank_cd` must score the whole table: cost scales
   with MATCHING rows, not corpus size. Real vocabularies are selective;
   real lexical cost sits far below this line. The lesson stands though:
   the GIN index finds candidates fast, but ranking them is linear in how
   many there are.
3. **The embedder dominates the vector path** (~18ms of a ~27ms wall). The
   fastest thing in this platform is now a Postgres ANN query.

![split](figures/search_split.png)

## Persist scaling

![persist](figures/persist_scaling.png)

Linear in chunk count at ~2.5ms/chunk plus ~7ms base: 2-chunk docs ~12ms,
8-chunk ~25ms, 20-chunk ~50ms. One transaction per document throughout;
19,990 chunks persisted with zero errors.

## The batch-token-budget fix (embedder memory)

Follow-up to the 1.6GiB serving-pod observation: ORT's arena grows to the
largest batch seen and never shrinks, and ingest sends batches of 32 ×
~480-token chunks — ~6× the token load the batch-32 knee was measured on
(40-token texts).

Measured on the embed node, fresh arena per batch size, 480-token texts:

| batch | throughput | peak RSS |
|---|---|---|
| 4 | 12.5 texts/s (6.0k tok/s) | 710MB |
| 8 | 11.9 texts/s (5.7k tok/s) | 947MB |
| 16, 32 | runs failed (likely node memory pressure beside the 1.6GB serving pod) | — |

**Batch 4 already saturates** — tokens/s is the invariant and 4 × 480
tokens reaches it. Batches beyond ~8 buy zero throughput and hundreds of MB
of permanent arena. Action: set `EMBED_BATCH_SIZE=8` on rag-ingest (same
throughput, arena ~950MB instead of 1.6GB+) and restart the embedder to
reset its arena. "Batch size is a token budget, not a count."
