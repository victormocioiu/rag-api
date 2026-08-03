"""Run the EnterpriseRAG-Bench questions against the live platform.

Produces the benchmark's official answers.jsonl (document_ids per
question, mapped back to dsid_ uuids via the ingest state file) and a
local Document Recall score -- plain set math over the gold sets, no LLM
judge required. Answer correctness/completeness need a generation layer
(part 4); the retrieval metric is what part 3 is accountable for.

    uv run --with httpx python bench/run_questions.py \\
        --questions ../EnterpriseRAG-Bench/questions.jsonl \\
        --api-url https://rag-api.<tailnet>.ts.net \\
        --tenant erb-v1 --state bench/state-erb-v1.jsonl \\
        --answers bench/answers-erb-v1.jsonl \\
        --json results/erb-amd-v1.json
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx


def load_doc_map(state_path: Path) -> dict[str, str]:
    doc_map: dict[str, str] = {}
    for line in state_path.read_text().splitlines():
        row = json.loads(line)
        if row.get("document_id"):
            doc_map[row["document_id"]] = row["dsid"]
    return doc_map


async def ask(client: httpx.AsyncClient, sem: asyncio.Semaphore,
              args, doc_map: dict[str, str], question: dict) -> dict:
    async with sem:
        t0 = time.monotonic()
        response = await client.post(
            f"{args.api_url}/search",
            headers={"x-tenant-slug": args.tenant},
            json={"query": question["question"], "k": args.chunk_k,
                  "mode": args.mode, "lexical_stopword_strip": True})
        response.raise_for_status()
        hits = response.json()["hits"]
    dsids: list[str] = []
    for hit in hits:  # already score-ordered; dedupe keeps best rank
        dsid = doc_map.get(hit["document_id"])
        if dsid and dsid not in dsids:
            dsids.append(dsid)
    dsids = dsids[:args.max_docs]
    gold = question.get("expected_doc_ids") or []
    return {
        "question_id": question["question_id"],
        "question_type": question["question_type"],
        "document_ids": dsids,
        "gold": gold,
        "hit": len(set(dsids) & set(gold)),
        "ms": round((time.monotonic() - t0) * 1000, 1),
    }


def aggregate(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["gold"]]
    recalls = [r["hit"] / len(r["gold"]) for r in scored]
    extras = [len(r["document_ids"]) - r["hit"] for r in scored]
    return {
        "n_questions": len(rows),
        "n_scored": len(scored),
        "document_recall": round(sum(recalls) / len(recalls), 4),
        "full_recall_rate": round(
            sum(1 for r in recalls if r == 1.0) / len(recalls), 4),
        "mean_extra_docs": round(sum(extras) / len(extras), 2),
    }


async def run(args) -> None:
    questions = [json.loads(line) for line in
                 Path(args.questions).read_text().splitlines()]
    doc_map = load_doc_map(Path(args.state))
    print(f"{len(questions)} questions, {len(doc_map)} ingested docs mapped")

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=120) as client:
        rows = await asyncio.gather(*(
            ask(client, sem, args, doc_map, q) for q in questions))

    Path(args.answers).write_text("".join(
        json.dumps({"question_id": r["question_id"],
                    "document_ids": r["document_ids"]}) + "\n"
        for r in rows))

    overall = aggregate(list(rows))
    per_type: dict[str, dict] = {}
    for qtype in sorted({r["question_type"] for r in rows}):
        subset = [r for r in rows if r["question_type"] == qtype]
        if any(r["gold"] for r in subset):
            per_type[qtype] = aggregate(subset)

    print(f"\ndocument recall: {overall['document_recall']} "
          f"(full-recall rate {overall['full_recall_rate']}) "
          f"over {overall['n_scored']} scored questions")
    for qtype, agg in per_type.items():
        print(f"  {qtype:>24}: recall {agg['document_recall']:.3f} "
              f"full {agg['full_recall_rate']:.3f} (n={agg['n_scored']})")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"overall": overall, "per_type": per_type,
             "chunk_k": args.chunk_k, "max_docs": args.max_docs,
             "rows": rows}, indent=1))
        print(f"wrote {args.json}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--tenant", default="erb-v1")
    p.add_argument("--state", default="bench/state.jsonl")
    p.add_argument("--answers", default="bench/answers.jsonl")
    p.add_argument("--json", default=None)
    p.add_argument("--chunk-k", type=int, default=40)
    p.add_argument("--mode", default="hybrid")
    p.add_argument("--max-docs", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args()
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
