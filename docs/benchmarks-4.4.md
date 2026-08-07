# Session 4.4 — the tricks bag, emptied properly

2026-08-07, overnight. Three slice experiments, one greedy combo, one
$2 intercept that redirected a $9 run, and a final number.

## The slice matrix (100-q, luna-judged, champion was 41.39)

| config | overall | verdict |
|---|---|---|
| sonnet-5 x rerank, k8 | 43.12 | model upgrade pays |
| haiku x rerank, k12 | 42.66 | reranked chunks 9-12 are GOOD chunks |
| haiku x completeness-prompt | 38.23 | instruction overload; a no |
| **sonnet-5 x rerank, k12** | **45.03** | the wins stack |

The k12 result rehabilitates context width: k16 was condemned when RRF
filled slots 9-16 with junk; the reranker fills them with evidence. Width
was never the villain -- selection was, in both directions.

The auto-chain was intercepted mid-wait for a $2 combo test before its
$9 full run: the combo won by 1.9 and the full run went out at the true
argmax. Doctrine paid in cash.

## The final run (full 500, sonnet-5 x k12 x rerank, luna-judged)

| | value | prior best |
|---|---|---|
| **Overall** | **46.71** | 42.11 |
| Correctness | 53.0 | 46.4 |
| Completeness | 56.5 | 52.8 |
| Document Recall | 69.6 | 69.7 (unchanged -- answering-side gain) |
| Invalid extras | 9.0 | 9.0 |

Leaderboard: **7th of 14, 1.71 points behind Azure AI Search (48.42),
2.25 behind Amazon Q (48.96), 3.5 behind RAGFlow (50.24).** Above:
NVIDIA (37.7), AnythingLLM, Verba, and every framework default -- by 20.

The campaign in one line: **32.44 -> 38.22 -> 42.11 -> 46.71** (+14.3),
via model ladder, reranker, and the sonnet-k12 combo -- with five
measured negatives published along the way (k16-unranked, prompt-only,
multi-query, agent-v1, luna-variants).

## What remains (part 3's opening inventory)

- HyDE slice ($1.50): the last cheap unknown, aimed at semantic
- The planning agent: project/completeness blocks, the last structural
  lever; realistic +2-4 -- which is exactly the Azure gap
- The submission: answers file ready (bench/answers-submission-final
  .jsonl), luna-judged with a published gpt-5.4 calibration (delta 0.37)

## Addendum — HyDE, the last cheap trick (4.4b)

Hallucinate a plausible answer, embed it as a PASSAGE, search
document-space with it -- one variable against the 45.03 champion.
Result: **44.5, a wash**, and the isolation is the finding: semantic
recall 44.0 vs 44.0, semantic correctness 28.0 vs 28.0 -- IDENTICAL.
The fake document's embedding lands in the same neighborhood the
question's does. The semantic wall is not a query/document-space
mismatch; it is the embedder's geometry, now confirmed from three
independent directions (multi-query, ef_search sweep, HyDE). Six
measured noes total; **46.71 stands as part 2's final number.** The
only remaining lever for semantic is a different embedder -- priced,
declined, and honest about it.
