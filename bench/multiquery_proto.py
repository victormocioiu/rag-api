"""Multi-query prototype: rewrite -> union-retrieve -> rerank -> answer.
Slice-only; the judge decides whether this becomes a platform flag."""
# ruff: noqa: ASYNC230, SIM115, BLE001 -- throwaway bench script:
# blocking local file appends are microseconds and the ledger must flush;
# the retry loop deliberately catches everything

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, "src")
from rag_api.llm import SYSTEM_PROMPT, AnswerLLM, build_user_prompt

API = "https://rag-api.tail17a16a.ts.net"
RERANK = "https://rag-reranker.tail17a16a.ts.net"

REWRITE_PROMPT = (
    "Generate 3 alternative search queries for this question: two "
    "rephrasings using DIFFERENT vocabulary than the original, and one "
    "keyword-only variant (3-6 terms). One per line, no numbering, no "
    "commentary.\n\nQuestion: {q}"
)


async def main():
    subset = set(Path("bench/ladder-subset.txt").read_text().split())
    questions = [q for q in
                 (json.loads(l) for l in Path("../EnterpriseRAG-Bench/questions.jsonl").read_text().splitlines())
                 if q["question_id"] in subset]
    state = {json.loads(l)["document_id"]: json.loads(l)["dsid"]
             for l in open("bench/state-erb-v1.jsonl")
             if json.loads(l).get("document_id")}
    out_path = Path("bench/answers-ladder-mq.jsonl")
    done = set()
    if out_path.exists():
        done = {json.loads(l)["question_id"] for l in open(out_path)}

    llm = AnswerLLM("openai", os.environ["LLM_API_KEY"],
                    "anthropic/claude-haiku-4.5",
                    base_url="https://openrouter.ai/api/v1", max_tokens=8192)
    sem = asyncio.Semaphore(2)  # reranker pod is the single-file stage
    fh = out_path.open("a")
    lock = asyncio.Lock()
    stats = {"n": 0}

    async def one(client, q):
        qid = q["question_id"]
        # 1. rewrites
        parts = [d async for d in llm.stream(
            "You expand search queries.", REWRITE_PROMPT.format(q=q["question"]))]
        rewrites = [l.strip() for l in "".join(parts).splitlines() if l.strip()][:3]
        queries = [q["question"], *rewrites]
        # 2. union retrieval, RRF across lists
        scores: dict[int, float] = {}
        info: dict[int, dict] = {}
        for query in queries:
            r = await client.post(f"{API}/search",
                                  headers={"x-tenant-slug": "erb-v1"},
                                  json={"query": query, "k": 50,
                                        "mode": "hybrid",
                                        "lexical_backend": "bm25",
                                        "vector_weight": 0.3})
            r.raise_for_status()
            for rank, h in enumerate(r.json()["hits"], 1):
                scores[h["chunk_id"]] = scores.get(h["chunk_id"], 0) + 1.0 / (60 + rank)
                info[h["chunk_id"]] = h
        fused = sorted(scores, key=lambda c: -scores[c])[:50]
        # 3. rerank the fused window against the ORIGINAL question
        async with sem:
            rr = await client.post(f"{RERANK}/rerank",
                                   json={"query": q["question"],
                                         "texts": [info[c]["content"] for c in fused]})
        order = ([fused[x["index"]] for x in rr.json()["results"]]
                 if rr.status_code == 200 else fused)
        # 4. answer from top-8; docs from reranked order
        docs, seen = [], set()
        for c in order:
            d = state.get(info[c]["document_id"])
            if d and d not in seen:
                seen.add(d); docs.append(d)
        prompt = build_user_prompt(q["question"], [
            {"heading_path": info[c]["heading_path"],
             "content": info[c]["content"]} for c in order[:8]])
        for attempt in range(4):
            try:
                parts = [d async for d in llm.stream(SYSTEM_PROMPT, prompt)]
                answer = "".join(parts).strip()
                if answer:
                    break
            except Exception:
                await asyncio.sleep(3 * 2 ** attempt)
        else:
            return
        async with lock:
            fh.write(json.dumps({"question_id": qid, "answer": answer,
                                 "document_ids": docs[:10],
                                 "rewrites": rewrites}) + "\n")
            fh.flush()
            stats["n"] += 1
            if stats["n"] % 10 == 0:
                print(f"{stats['n']} done", flush=True)

    async with httpx.AsyncClient(timeout=300) as client:
        await asyncio.gather(*(one(client, q) for q in questions
                               if q["question_id"] not in done))
    await llm.aclose()
    print("mq answers:", sum(1 for _ in open(out_path)))

asyncio.run(main())
