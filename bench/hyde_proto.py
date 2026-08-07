"""HyDE slice: hallucinate an answer, embed it as a PASSAGE, search with
that. One variable vs the sonnet-k12 champion (45.03)."""
# ruff: noqa: ASYNC230, ASYNC221, SIM115, BLE001, PLC0206 -- throwaway bench script

import asyncio
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, "src")
from rag_api.llm import SYSTEM_PROMPT, AnswerLLM, build_user_prompt

S = Path(os.environ.get("SCRATCH", "/tmp"))
EMBED = "https://rag-embedder.tail17a16a.ts.net"
RERANK = "https://rag-reranker.tail17a16a.ts.net"

HYDE_PROMPT = (
    "Write a short excerpt (2-4 sentences) of a plausible internal company "
    "document that would directly answer this question. Invent specifics "
    "freely -- style and vocabulary matter, truth does not. No preamble, "
    "no meta, just the excerpt.\n\nQuestion: {q}"
)


async def main():
    subset = set(Path("bench/ladder-subset.txt").read_text().split())
    questions = [q for q in
                 (json.loads(l) for l in Path("../EnterpriseRAG-Bench/questions.jsonl").read_text().splitlines())
                 if q["question_id"] in subset]
    state = {json.loads(l)["document_id"]: json.loads(l)["dsid"]
             for l in open("bench/state-erb-v1.jsonl")
             if json.loads(l).get("document_id")}

    llm = AnswerLLM("openai", os.environ["LLM_API_KEY"],
                    "anthropic/claude-haiku-4.5",
                    base_url="https://openrouter.ai/api/v1", max_tokens=512)

    # 1. hypotheticals
    hyde: dict[str, str] = {}
    sem = asyncio.Semaphore(6)
    async def hallucinate(q):
        async with sem:
            parts = [d async for d in llm.stream(
                "You draft plausible document excerpts.",
                HYDE_PROMPT.format(q=q["question"]))]
            hyde[q["question_id"]] = "".join(parts).strip()
    await asyncio.gather(*(hallucinate(q) for q in questions))
    print(f"hypotheticals: {len(hyde)}", flush=True)

    # 2. embed as PASSAGES
    embs: dict[str, list[float]] = {}
    async with httpx.AsyncClient(timeout=120) as client:
        qids = [q["question_id"] for q in questions]
        for i in range(0, len(qids), 16):
            batch = qids[i:i + 16]
            r = await client.post(f"{EMBED}/embed", json={
                "texts": [hyde[qid] for qid in batch],
                "input_type": "passage"})
            r.raise_for_status()
            for qid, e in zip(batch, r.json()["embeddings"]):
                embs[qid] = e
    print("embedded", flush=True)

    # 3. vector search with hypothetical embeddings (direct PG)
    sql = ["SET hnsw.ef_search = 400;",
           "CREATE TEMP TABLE qe (qid text, emb halfvec(384));"]
    for qid, e in embs.items():
        vec = "[" + ",".join(f"{x:.8f}" for x in e) + "]"
        sql.append(f"INSERT INTO qe VALUES ('{qid}', '{vec}'::halfvec);")
    sql.append("""
SELECT 'HYDE', q.qid, w.rn, w.id, w.document_id
FROM qe q CROSS JOIN LATERAL (
  SELECT id, document_id, row_number() OVER () AS rn FROM (
    SELECT id, document_id FROM chunks
    ORDER BY embedding <#> q.emb LIMIT 150) x) w;""")
    out = subprocess.run(
        ["kubectl", "exec", "-i", "-n", "postgres", "rag-pg-1", "-c",
         "postgres", "--", "psql", "-U", "postgres", "-d", "app",
         "-t", "-A", "-F", ","],
        input="\n".join(sql).encode(), capture_output=True, timeout=1800,
        check=True)
    hyde_cands: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for line in out.stdout.decode().splitlines():
        p = line.split(",")
        if len(p) == 5 and p[0] == "HYDE":
            hyde_cands[p[1]].append((p[3], p[4]))
    print("hyde retrieval done", flush=True)

    # 4. fuse with the existing bm25-150 dump (same subset)
    bm25: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for line in open(f"{S}/cand_bm25.csv"):
        p = line.strip().split(",")
        if len(p) == 5 and p[0] == "BM25":
            bm25[p[1]].append((p[3], p[4]))
    fused: dict[str, list[str]] = {}
    docof: dict[str, str] = {}
    for qid in hyde_cands:
        scores: dict[str, float] = {}
        for rank, (cid, doc) in enumerate(bm25.get(qid, []), 1):
            scores[cid] = scores.get(cid, 0) + 1.0 / (60 + rank)
            docof[cid] = doc
        for rank, (cid, doc) in enumerate(hyde_cands[qid], 1):
            scores[cid] = scores.get(cid, 0) + 0.3 / (60 + rank)
            docof[cid] = doc
        fused[qid] = sorted(scores, key=lambda c: -scores[c])[:50]

    # 5. contents for the union
    need = sorted({c for cc in fused.values() for c in cc})
    copy_sql = ("COPY (SELECT id, document_id, replace(replace(content, "
                "E'\\n', ' '), ',', ';') FROM chunks WHERE id IN ("
                + ",".join(need) + ")) TO STDOUT WITH (FORMAT csv);")
    out = subprocess.run(
        ["kubectl", "exec", "-i", "-n", "postgres", "rag-pg-1", "-c",
         "postgres", "--", "psql", "-U", "postgres", "-d", "app"],
        input=copy_sql.encode(), capture_output=True, timeout=1800,
        check=True)
    content: dict[str, str] = {}
    for row in csv.reader(out.stdout.decode().splitlines()):
        if len(row) >= 3:
            content[row[0]] = row[2]
    print(f"contents: {len(content)}", flush=True)

    # 6. rerank via the live service + 7. sonnet answers
    answers_path = Path("bench/answers-ladder-hyde.jsonl")
    done = set()
    if answers_path.exists():
        done = {json.loads(l)["question_id"] for l in open(answers_path)}
    sonnet = AnswerLLM("openai", os.environ["LLM_API_KEY"],
                       "anthropic/claude-sonnet-5",
                       base_url="https://openrouter.ai/api/v1",
                       max_tokens=8192)
    fh = answers_path.open("a")
    lock = asyncio.Lock()
    rr_sem = asyncio.Semaphore(2)
    n = [0]

    async def one(client, q):
        qid = q["question_id"]
        if qid in done or qid not in fused:
            return
        cands = fused[qid]
        async with rr_sem:
            rr = await client.post(f"{RERANK}/rerank", json={
                "query": q["question"],
                "texts": [content.get(c, "") for c in cands]})
        order = ([cands[x["index"]] for x in rr.json()["results"]]
                 if rr.status_code == 200 else cands)
        docs, seen = [], set()
        for c in order:
            d = state.get(docof.get(c))
            if d and d not in seen:
                seen.add(d); docs.append(d)
        prompt = build_user_prompt(q["question"], [
            {"heading_path": "", "content": content.get(c, "")}
            for c in order[:12]])
        for attempt in range(4):
            try:
                parts = [x async for x in sonnet.stream(SYSTEM_PROMPT, prompt)]
                a = "".join(parts).strip()
                if a:
                    break
            except Exception:
                await asyncio.sleep(3 * 2 ** attempt)
        else:
            return
        async with lock:
            fh.write(json.dumps({"question_id": qid, "answer": a,
                                 "document_ids": docs[:10],
                                 "hyde": hyde.get(qid, "")}) + "\n")
            fh.flush()
            n[0] += 1
            if n[0] % 20 == 0:
                print(f"{n[0]} answered", flush=True)

    async with httpx.AsyncClient(timeout=300) as client:
        await asyncio.gather(*(one(client, q) for q in questions))
    await llm.aclose()
    await sonnet.aclose()
    print("hyde answers:", sum(1 for _ in open(answers_path)))

asyncio.run(main())
