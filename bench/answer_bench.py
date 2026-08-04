"""Generate official EnterpriseRAG-Bench answers: retrieval through the
live platform, synthesis with the platform's own prompt + model.

Retrieval hits /search on the live API (hybrid, bm25, vector weight 0.3
-- the platform config); the top-8 chunks feed rag_api.llm's SYSTEM_PROMPT
/ build_user_prompt verbatim, so the answers are what /chat would say,
minus the per-tenant demo budget that a 500-question batch has no
business consuming. Output rows carry both `answer` and `document_ids`
(top-10 docs from the same retrieval) -- the benchmark's full submission
format. Resumable: rows append to the answers file, present qids skip.

    LLM_API_KEY=... LLM_BASE_URL=https://openrouter.ai/api/v1 \\
    LLM_MODEL=mistralai/mistral-small-3.2-24b-instruct \\
    uv run --with httpx python bench/answer_bench.py \\
        --questions ../EnterpriseRAG-Bench/questions.jsonl \\
        --api-url https://rag-api.<tailnet>.ts.net --tenant erb-v1 \\
        --state bench/state-erb-v1.jsonl \\
        --answers bench/answers-official.jsonl
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from rag_api.llm import SYSTEM_PROMPT, AnswerLLM, LLMError, build_user_prompt


def load_doc_map(state_path: Path) -> dict[str, str]:
    doc_map: dict[str, str] = {}
    for line in state_path.read_text().splitlines():
        row = json.loads(line)
        if row.get("document_id"):
            doc_map[row["document_id"]] = row["dsid"]
    return doc_map


async def one(client: httpx.AsyncClient, llm: AnswerLLM,
              sem: asyncio.Semaphore, args, doc_map: dict[str, str],
              question: dict, out_fh, lock: asyncio.Lock,
              stats: dict) -> None:
    async with sem:
        response = await client.post(
            f"{args.api_url}/search",
            headers={"x-tenant-slug": args.tenant},
            json={"query": question["question"], "k": 50, "mode": "hybrid",
                  "lexical_backend": "bm25", "vector_weight": 0.3})
        response.raise_for_status()
        hits = response.json()["hits"]

        dsids: list[str] = []
        for hit in hits:
            dsid = doc_map.get(hit["document_id"])
            if dsid and dsid not in dsids:
                dsids.append(dsid)
        dsids = dsids[:10]

        prompt = build_user_prompt(
            question["question"],
            [{"heading_path": h["heading_path"], "content": h["content"]}
             for h in hits[:8]])
        answer = ""
        for attempt in range(4):
            try:
                parts = [d async for d in llm.stream(SYSTEM_PROMPT, prompt)]
                answer = "".join(parts).strip()
                break
            except LLMError as exc:
                if attempt == 3:
                    async with lock:
                        stats["errors"] += 1
                        print(f"  ERROR {question['question_id']}: "
                              f"{str(exc)[:120]}", flush=True)
                    return
                await asyncio.sleep(3 * 2 ** attempt)

        async with lock:
            out_fh.write(json.dumps({
                "question_id": question["question_id"],
                "answer": answer,
                "document_ids": dsids}) + "\n")
            out_fh.flush()
            stats["done"] += 1
            if stats["done"] % 25 == 0:
                dt = time.monotonic() - stats["t0"]
                print(f"  {stats['done']:>4} answered "
                      f"({stats['done'] / dt:.1f} q/s, "
                      f"errors {stats['errors']})", flush=True)


async def run(args) -> None:
    questions = [json.loads(line) for line in
                 Path(args.questions).read_text().splitlines()]
    done: set[str] = set()
    answers_path = Path(args.answers)
    if answers_path.exists():
        done = {json.loads(line)["question_id"]
                for line in answers_path.read_text().splitlines()}
        print(f"resume: {len(done)} already answered")
    todo = [q for q in questions if q["question_id"] not in done]
    doc_map = load_doc_map(Path(args.state))
    print(f"{len(todo)} to answer, model {os.environ.get('LLM_MODEL')}")

    llm = AnswerLLM(
        provider="openai",
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ.get(
            "LLM_MODEL", "mistralai/mistral-small-3.2-24b-instruct"),
        base_url=os.environ.get("LLM_BASE_URL"),
        max_tokens=1024)
    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    stats = {"done": 0, "errors": 0, "t0": time.monotonic()}
    async with httpx.AsyncClient(timeout=180) as client:
        with answers_path.open("a") as out_fh:  # noqa: ASYNC230 -- tiny local appends; the ledger must flush eagerly
            await asyncio.gather(*(
                one(client, llm, sem, args, doc_map, q, out_fh, lock, stats)
                for q in todo))
    await llm.aclose()
    dt = time.monotonic() - stats["t0"]
    print(f"\ndone: {stats['done']} answered in {dt / 60:.1f} min, "
          f"{stats['errors']} errors")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--tenant", default="erb-v1")
    p.add_argument("--state", default="bench/state-erb-v1.jsonl")
    p.add_argument("--answers", default="bench/answers-official.jsonl")
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args()
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
