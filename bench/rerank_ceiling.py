"""Measure the reranker ceiling: for every scored question, how deep in
the VECTOR candidate list does the first gold chunk sit?

A reranker can only promote what candidate generation returns, so the
share of questions with gold within width W is a hard ceiling on what
rerank-over-top-W can score. Runs against the live embedder (tailnet)
and Postgres (kubectl exec psql), no serving changes.

    uv run --with httpx python bench/rerank_ceiling.py \\
        --questions ../EnterpriseRAG-Bench/questions.jsonl \\
        --state bench/state-erb-v1.jsonl --json results/erb-ceiling-v1.json
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

EMBED_URL = "https://rag-embedder.tail17a16a.ts.net/embed"
WIDTHS = (50, 100, 200, 500, 1000)


def embed_questions(questions: list[dict]) -> list[list[float]]:
    out: list[list[float]] = []
    with httpx.Client(timeout=120) as client:
        for i in range(0, len(questions), 16):
            batch = [q["question"] for q in questions[i:i + 16]]
            r = client.post(EMBED_URL, json={"texts": batch,
                                             "input_type": "query"})
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
    return out


def build_sql(questions, embeddings, dsid_to_doc) -> str:
    lines = [
        "SET hnsw.ef_search = 1000;",
        "CREATE TEMP TABLE qe (qid text, emb halfvec(384), gold uuid[]);",
    ]
    for q, emb in zip(questions, embeddings):
        gold = [dsid_to_doc[d] for d in q["expected_doc_ids"]
                if d in dsid_to_doc]
        if not gold:
            continue
        vec = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
        arr = ",".join(f"'{g}'" for g in gold)
        lines.append(
            f"INSERT INTO qe VALUES ('{q['question_id']}', "
            f"'{vec}'::halfvec, ARRAY[{arr}]::uuid[]);")
    lines.append("""
SELECT q.qid, coalesce(r.best, -1)
FROM qe q
LEFT JOIN LATERAL (
    SELECT min(rnk) AS best FROM (
        SELECT row_number() OVER () AS rnk, document_id FROM (
            SELECT document_id FROM chunks
            WHERE tenant_id = (SELECT id FROM tenants WHERE slug = 'erb-v1')
            ORDER BY embedding <#> q.emb LIMIT 1000
        ) w
    ) t WHERE t.document_id = ANY(q.gold)
) r ON true;""")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", required=True)
    p.add_argument("--state", default="bench/state-erb-v1.jsonl")
    p.add_argument("--json", default="results/erb-ceiling-v1.json")
    a = p.parse_args()

    questions = [json.loads(line) for line in
                 Path(a.questions).read_text().splitlines()
                 if json.loads(line).get("expected_doc_ids")]
    dsid_to_doc = {}
    for line in Path(a.state).read_text().splitlines():
        row = json.loads(line)
        if row.get("document_id"):
            dsid_to_doc[row["dsid"]] = row["document_id"]
    print(f"{len(questions)} questions with gold docs")

    t0 = time.time()
    embeddings = embed_questions(questions)
    print(f"embedded in {time.time() - t0:.0f}s")

    sql = build_sql(questions, embeddings, dsid_to_doc)
    t0 = time.time()
    result = subprocess.run(
        ["kubectl", "exec", "-i", "-n", "postgres", "rag-pg-1",
         "-c", "postgres", "--", "psql", "-U", "postgres", "-d", "app",
         "-t", "-A", "-F", ","],
        input=sql.encode(), capture_output=True, timeout=3600,
        check=False)
    if result.returncode != 0:
        print(result.stderr.decode()[-2000:])
        return 1
    print(f"postgres pass in {time.time() - t0:.0f}s")

    ranks: dict[str, int] = {}
    for line in result.stdout.decode().splitlines():
        if "," in line:
            qid, best = line.rsplit(",", 1)
            try:
                ranks[qid] = int(best)
            except ValueError:
                continue
    qtype = {q["question_id"]: q["question_type"] for q in questions}
    n = len(ranks)
    print(f"\n{n} questions measured; gold-chunk depth in vector list:")
    curve = {}
    for width in WIDTHS:
        hit = sum(1 for r in ranks.values() if 0 < r <= width)
        curve[width] = round(hit / n, 4)
        print(f"  within top-{width:>5}: {hit:>3} ({hit / n:.1%})")
    beyond = sum(1 for r in ranks.values() if r < 0)
    print(f"  beyond top-1000: {beyond} ({beyond / n:.1%}) "
          f"-- unrecoverable by reranking")

    per_type: dict[str, dict] = {}
    for t in sorted(set(qtype.values())):
        sub = [r for qid, r in ranks.items() if qtype[qid] == t]
        if sub:
            per_type[t] = {
                "n": len(sub),
                "within_200": round(
                    sum(1 for r in sub if 0 < r <= 200) / len(sub), 3),
                "beyond_1000": round(
                    sum(1 for r in sub if r < 0) / len(sub), 3),
            }
            print(f"  {t:>24}: within-200 {per_type[t]['within_200']:.1%}  "
                  f"beyond-1000 {per_type[t]['beyond_1000']:.1%}")

    Path(a.json).write_text(json.dumps(
        {"curve": curve, "per_type": per_type, "ranks": ranks}, indent=1))
    print(f"wrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
