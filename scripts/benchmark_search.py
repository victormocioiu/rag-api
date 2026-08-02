"""Session 3.2: persist + search benchmarks against the live platform.
stdlib only -- runs from any pod.

Seeds synthetic documents through the REAL pipeline (rag-ingest -> embed ->
persist), pausing at corpus-size checkpoints to measure search latency per
mode. Persist scaling falls out of the ingest responses along the way.

    python scripts/benchmark_search.py \\
        --ingest-url http://rag-ingest.rag.svc.cluster.local \\
        --api-url http://rag-api.rag.svc.cluster.local \\
        --docs 2000 --checkpoints 100,500,1000,2000 \\
        --json results/search-amd-v1.json
"""

import argparse
import io
import json
import statistics
import time
import urllib.request
import uuid
from pathlib import Path

WORDS = ("retrieval", "augmented", "generation", "document", "chunking",
         "embedding", "vector", "storage", "billing", "refund", "policy",
         "invoice", "support", "customer", "onboarding", "quarterly", "report",
         "kubernetes", "postgres", "latency")

QUERIES = [
    ("keyword", "refund policy invoice"),
    ("keyword", "kubernetes postgres latency"),
    ("natural", "what is the policy for customer refunds?"),
    ("natural", "how does the onboarding process work for new customers?"),
    ("keyword", "quarterly onboarding report"),
    ("natural", "where are the embedding vectors stored?"),
]


def make_doc(i: int, sections: int) -> bytes:
    parts = [f"# Synthetic doc {i}"]
    for s in range(sections):
        parts.append(f"\n## Topic {s + 1}\n")
        for p in range(3):
            words = [WORDS[(i * 13 + s * 7 + p * 3 + j) % len(WORDS)]
                     for j in range(90)]
            parts.append(" ".join(words) + f" (doc-{i}-s{s}-p{p})")
    return "\n\n".join(parts).encode()


def post_ingest(url: str, data: bytes) -> dict:
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="file"; filename="d.md"\r\n')
    body.write(b"Content-Type: text/markdown\r\n\r\n")
    body.write(data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{url.rstrip('/')}/ingest?include_text=false",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def post_search(url: str, query: str, mode: str) -> dict:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/search",
        data=json.dumps({"query": query, "mode": mode}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def bench_search(api_url: str, corpus_chunks: int, reps: int) -> list[dict]:
    rows = []
    for mode in ("hybrid", "vector", "lexical"):
        walls, embeds, dbs = [], [], []
        for r in range(reps):
            _, query = QUERIES[r % len(QUERIES)]
            t0 = time.perf_counter()
            resp = post_search(api_url, query, mode)
            walls.append((time.perf_counter() - t0) * 1000)
            embeds.append(resp["timings_ms"].get("embed_query", 0))
            dbs.append(resp["timings_ms"].get("search", 0))
        walls.sort()
        rows.append({
            "corpus_chunks": corpus_chunks, "mode": mode, "reps": reps,
            "wall_p50_ms": round(statistics.median(walls), 1),
            "wall_p95_ms": round(walls[int(len(walls) * 0.95) - 1], 1),
            "embed_query_p50_ms": round(statistics.median(embeds), 1),
            "db_p50_ms": round(statistics.median(dbs), 1),
        })
        print(f"    {mode:>8}: wall p50 {rows[-1]['wall_p50_ms']}ms "
              f"(embed {rows[-1]['embed_query_p50_ms']} / "
              f"db {rows[-1]['db_p50_ms']})")
    return rows


def run(ingest_url: str, api_url: str, docs: int,
        checkpoints: list[int], out_path: str | None) -> None:
    persists: list[dict] = []
    searches: list[dict] = []
    corpus_chunks = 0
    seeded = 0
    t_start = time.time()
    for checkpoint in checkpoints:
        while seeded < checkpoint:
            sections = (1, 4, 10)[seeded % 3]  # varied sizes for persist scaling
            resp = post_ingest(ingest_url, make_doc(seeded, sections))
            corpus_chunks += resp["n_chunks"]
            persists.append({"n_chunks": resp["n_chunks"],
                             "persist_ms": resp["timings_ms"].get("persist", 0),
                             "embed_ms": resp["timings_ms"].get("embed", 0)})
            seeded += 1
        elapsed = time.time() - t_start
        print(f"  checkpoint {checkpoint} docs / {corpus_chunks} chunks "
              f"({elapsed:.0f}s elapsed)")
        searches.extend(bench_search(api_url, corpus_chunks, reps=24))

    if out_path:
        Path(out_path).write_text(json.dumps(
            {"persist": persists, "search": searches,
             "docs": seeded, "chunks": corpus_chunks}, indent=1))
        print(f"\nwrote {out_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ingest-url", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--docs", type=int, default=2000)
    p.add_argument("--checkpoints", default="100,500,1000,2000")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    checkpoints = [int(x) for x in a.checkpoints.split(",")]
    assert checkpoints[-1] <= a.docs or True
    run(a.ingest_url, a.api_url, a.docs, checkpoints, a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
