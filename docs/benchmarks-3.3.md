# Session 3.3 — the eval harness: six questions, answered

2026-08-02. 42-document corpus with **planted markers** (unique tokens like
`qzmd4x1v` inside facts), 104 queries across six classes, run against the
LIVE cluster — every ingest goes through rag-ingest → rag-embedder →
rag-api → Postgres, exactly like production traffic. A query is answered
correctly if a returned chunk contains its marker; markers make ground
truth configuration-agnostic, because however the document was chunked, the
marker is in exactly one place.

**Tenant-per-ablation**: each ingest-side configuration gets its own tenant
and the same corpus is re-ingested with one knob flipped. RLS — the same
mechanism that isolates customers — isolates the ablations. Search-side
ablations (mode, stopword strip) reuse the base tenant: no re-ingest.

Corpus: 20 markdown manuals (6 sections each), 6 documents with 30-row
tables, 8 multilingual docs (de/fr/ro/es), 8 PDFs with font-size headings.
Query classes: natural (n=40), keyword (20), table (12), pdf (16),
same-language ×4 (8), cross-lingual (8). Ingest of the full corpus takes
~30s per configuration; the whole 7-config × 42-doc, 12-pass × 104-query
run finishes in about six minutes.

Metrics: recall@k = share of queries whose marker chunk appears in the top
k; MRR = mean of 1/rank of the first correct chunk (1.0 = always first).

## Everything on one axis

![mrr](figures/eval_mrr.png)

All ingest configs scored with the platform search (hybrid, BM25 arm,
vector weight 0.3):

| configuration | chunks | r@1 | r@3 | MRR |
|---|---|---|---|---|
| base (structural, pypdfium2, grid) | 174 | 0.91 | 0.92 | 0.918 |
| token chunking | 68 | 0.92 | 0.92 | 0.923 |
| no heading paths | 174 | 0.85 | 0.92 | 0.880 |
| no overlap | 174 | 0.90 | 0.92 | 0.913 |
| tables as pairs | 172 | **0.92** | 0.92 | **0.923** |
| pdf: pypdf | 150 | 0.91 | 0.92 | 0.918 |
| pdf: hybrid router | 174 | 0.91 | 0.92 | 0.918 |
| search: vector only | — | 0.82 | 0.91 | 0.865 |
| search: lexical only (BM25) | — | 0.92 | 0.92 | 0.923 |
| search: tsquery + strip (comparison) | — | 0.85 | 0.85 | 0.846 |
| search: hybrid (BM25, w=0.3) | — | 0.91 | 0.92 | 0.918 |

The 0.92 ceiling is exactly the 8 cross-lingual queries (96/104 =
0.923) — every English-answerable query is answered, and the corpus
stops discriminating on RECALL. The ablation signal moves into RANKING
(r@1/MRR per class), which is where the verdicts below now read from.

![configs](figures/eval_configs.png)

## The six registered questions

### 1. Structural vs token chunking

On marker recall the two tie (0.92 both, MRR 0.923 vs 0.918) — BM25
finds the fact either way. The decision is entirely about what you hand
the LLM: token chunking packs the corpus into 68 chunks instead of 174,
each ~3× bigger, so at k=8 it returns ~12% of its whole corpus per
query and burns 3× the context budget to deliver the same fact. The
eval measures "is the fact in what we retrieve"; structural delivers it
in a third of the tokens with headings attached. Verdict:
**structural** — the metric can't see context quality, so don't let a
recall tie fool you.

### 2. Heading paths: the single most load-bearing ingest knob

Dropping the heading-path prefix costs MRR 0.918 → 0.880 overall — and
the damage concentrates exactly where structure is the only signal:

![tables](figures/eval_table_class.png)

Table queries drop from r@1 0.92 to **0.25** (MRR 0.958 → 0.625)
without heading paths. A chunk of `| dept-velvet-21 | qztb1x21v | 68 |`
rows still gets FOUND (BM25 matches the dept token), but ranking it
first needs the prepended `crimson churn report > Quarterly figures`
line — that's what carries "churn rate" for both arms. Verdict: **keep
heading paths on, always** — with BM25 they decide rank, not existence.

### 3. Overlap

MRR 0.918 → 0.913 without overlap: noise-level here. The planted facts are
single sentences that rarely straddle a boundary, which is precisely the
population overlap protects — this corpus under-exercises it. It costs
~6% extra tokens and protects against a real failure mode the eval can
barely see. Verdict: **keep it, cheap insurance**.

### 4. PDF engine choice

On this corpus the engines tie (pdf class 1.000 across the board) —
BM25 finds a planted marker in flat text just fine, so the eval cannot
separate them on recall. The verdict rests on what part 2 measured
directly: pypdf loses the font-size headings, and question 2 shows what
heading paths are worth wherever ranking gets hard. The hybrid router
scores identically to pypdfium2 here — all 8 PDFs are prose, the
path-count detector routes them there, and the tables-only pdfplumber
pass never fires. Verdict: **pypdfium2 via the hybrid router**, on
structural-quality grounds the marker metric is too blunt to reward.

### 5. Tables: grid vs pairs

Pairs is the only config that goes perfect on tables (r@1 1.00, MRR
1.000 vs grid's 0.92/0.958) and ties for best overall MRR (0.923).
Row-as-sentence ("department: dept-velvet-21. q3 churn rate:
qztb1x21v.") reads as prose to the embedder AND as clean term
statistics to BM25, where a pipe-delimited grid is soup to one and
noise to the other. Verdict: **pairs for retrieval**; grid
remains the right default when chunks are rendered back to humans or the
LLM needs whole-table context — this is a per-corpus knob, now with its
price measured from both sides (2.2 measured pairs' token cost, 3.3 its
retrieval win).

### 6. The lexical arm: BM25 vs plain Postgres FTS

![variants](figures/eval_search_variants.png)

The comparison the platform's arm choice rests on. Plain
`websearch_to_tsquery` ANDs every term, so natural questions demand
"what"/"is"/"the" appear in one chunk: lexical-only recall **0.19**,
natural-question class **0.00**. Query-side stopword stripping rescues
it to 0.85 — a workaround with a hand-rolled stopword list. The BM25
arm needs none of it: IDF makes stopwords cheap instead of mandatory,
and lexical-only scores **0.923 / MRR 0.923** with zero query
preprocessing. Verdict: **`lexical_backend=bm25`**; the tsquery arm
remains as the fallback for clusters without the extension, where the
strip flag is its best crutch. The margin here is small because the
corpus is; at 512K documents it is 0.66 vs 0.22 and 88ms vs 7.5s
(`benchmarks-3.5.md`, `benchmarks-3.2.md`).

## What the harness caught that we didn't plant

![classes](figures/eval_per_class.png)

**Cross-lingual retrieval fails on e5-small.** Same-language retrieval
is perfect in all four languages (8/8 — German questions find German
chunks). But English questions against non-English documents: 0/8 at
the platform config. (With the vector arm at full weight it manages
exactly one: Spanish "el inventario anual" ↔ "the annual inventory" — a
cognate, not cross-lingual understanding; lexical arms obviously cannot
cross languages at all.)
"Multilingual model" means each language is embedded well, not that the
languages share a semantic space tightly enough for 384-dim retrieval.
If cross-lingual matters, translate at ingest or query time — don't
expect the embedder to do it.

English fact-lookup saturates (natural/keyword/pdf all 1.00 on base) —
which is also the honest limit of marker-based ground truth with a real
lexical arm: unique planted tokens are exactly what BM25 is best at, so
the corpus stops discriminating on recall and the ranking columns carry
the signal —
by design: markers verify the pipeline delivers, while tables,
cross-lingual, and the ablations do the discriminating.

## Honest limits

- 174 chunks is retrieval-easy; ranking effects (grid vs pairs, heading
  paths) transfer to scale, absolute recall numbers do not.
- Marker-in-chunk is retrieval ground truth, not answer quality — no LLM
  in the loop. That's 3.4's job (EnterpriseRAG-Bench).
- One corpus, synthetic, English-question-biased. The per-class table is
  the honest view; the headline number flatters.

Reproduce:

```bash
uv run --with fpdf2 python eval/build_corpus.py --out eval/corpus
uv run python eval/run_eval.py \
    --ingest-url https://rag-ingest.<tailnet>.ts.net \
    --api-url https://rag-api.<tailnet>.ts.net \
    --json results/eval-amd-v1.json
uv run --with matplotlib --with seaborn python eval/plot_eval.py \
    results/eval-amd-v1.json --out docs/figures
```
