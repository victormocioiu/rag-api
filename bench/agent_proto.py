"""Agent-loop prototype: retrieve -> assess gaps -> targeted re-search
(max 2 rounds) -> rerank the pooled evidence -> answer. Slice-only.

Aimed at the structurally-unsolved blocks: project_related and
completeness, where the answer spans documents no single retrieval
round surfaces together."""
# ruff: noqa: ASYNC230, SIM115, BLE001 -- throwaway bench script

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

ASSESS_PROMPT = (
    "You are gathering evidence to answer a question. Below is the "
    "evidence found so far. If it is sufficient to answer fully, reply "
    "exactly DONE. Otherwise reply with 1-2 lines, each of the form "
    "SEARCH: <keyword query>, targeting the SPECIFIC missing "
    "information. Different vocabulary than earlier searches helps.\n\n"
    "Question: {q}\n\nEvidence so far:\n{ev}"
)


async def search(client, query, k=20):
    r = await client.post(f"{API}/search",
                          headers={"x-tenant-slug": "erb-v1"},
                          json={"query": query, "k": k, "mode": "hybrid",
                                "lexical_backend": "bm25",
                                "vector_weight": 0.3})
    r.raise_for_status()
    return r.json()["hits"]


async def main():
    subset = set(Path("bench/ladder-subset.txt").read_text().split())
    questions = [q for q in
                 (json.loads(l) for l in Path("../EnterpriseRAG-Bench/questions.jsonl").read_text().splitlines())
                 if q["question_id"] in subset]
    state = {json.loads(l)["document_id"]: json.loads(l)["dsid"]
             for l in open("bench/state-erb-v1.jsonl")
             if json.loads(l).get("document_id")}
    out_path = Path("bench/answers-ladder-agent.jsonl")
    done = set()
    if out_path.exists():
        done = {json.loads(l)["question_id"] for l in open(out_path)}

    llm = AnswerLLM("openai", os.environ["LLM_API_KEY"],
                    "anthropic/claude-haiku-4.5",
                    base_url="https://openrouter.ai/api/v1", max_tokens=8192)
    rerank_sem = asyncio.Semaphore(2)
    fh = out_path.open("a")
    lock = asyncio.Lock()
    stats = {"n": 0, "rounds": 0}

    async def one(client, q):
        qid = q["question_id"]
        pool: dict[int, dict] = {}
        for h in await search(client, q["question"]):
            pool[h["chunk_id"]] = h
        searches = [q["question"]]
        for _ in range(2):
            ev = "\n".join(f"- {h['content'][:280]}"
                           for h in list(pool.values())[:14])
            parts = [d async for d in llm.stream(
                "You plan evidence gathering.",
                ASSESS_PROMPT.format(q=q["question"], ev=ev))]
            plan = "".join(parts)
            new = [l.split("SEARCH:", 1)[1].strip()
                   for l in plan.splitlines() if "SEARCH:" in l][:2]
            if not new:
                break
            stats["rounds"] += 1
            for query in new:
                searches.append(query)
                for h in await search(client, query):
                    pool.setdefault(h["chunk_id"], h)
        ids = list(pool)
        async with rerank_sem:
            rr = await client.post(f"{RERANK}/rerank", json={
                "query": q["question"],
                "texts": [pool[c]["content"] for c in ids][:200]})
        order = ([ids[x["index"]] for x in rr.json()["results"]]
                 if rr.status_code == 200 else ids)
        docs, seen = [], set()
        for c in order:
            d = state.get(pool[c]["document_id"])
            if d and d not in seen:
                seen.add(d); docs.append(d)
        prompt = build_user_prompt(q["question"], [
            {"heading_path": pool[c]["heading_path"],
             "content": pool[c]["content"]} for c in order[:10]])
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
                                 "searches": searches}) + "\n")
            fh.flush()
            stats["n"] += 1
            if stats["n"] % 10 == 0:
                print(f"{stats['n']} done ({stats['rounds']} extra rounds)",
                      flush=True)

    async with httpx.AsyncClient(timeout=300) as client:
        await asyncio.gather(*(one(client, q) for q in questions
                               if q["question_id"] not in done))
    await llm.aclose()
    print("agent answers:", sum(1 for _ in open(out_path)))

asyncio.run(main())
