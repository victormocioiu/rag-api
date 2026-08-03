"""The eval harness: tenant-per-ablation, recall@k over planted markers.
stdlib only.

Each ingest-side configuration gets its OWN TENANT: the same corpus is
ingested per config with that config's knobs, and RLS guarantees the
ablations cannot contaminate each other. Search-side ablations (mode,
stopword strip) reuse the base tenant -- no re-ingest needed.

    python eval/run_eval.py \\
        --ingest-url https://rag-ingest.<tailnet>.ts.net \\
        --api-url https://rag-api.<tailnet>.ts.net \\
        --corpus eval/corpus --queries eval/queries.json \\
        --json results/eval-amd-v1.json
"""

import argparse
import io
import json
import time
import urllib.request
import uuid
from pathlib import Path

# ingest-side ablations: tenant slug -> extra /ingest query params
INGEST_CONFIGS = {
    "eval-base": "",
    "eval-token": "&strategy=token",
    "eval-noheads": "&heading_paths=false",
    "eval-nooverlap": "&overlap_tokens=0",
    "eval-pairs": "&table_mode=pairs",
    "eval-pdf-pypdf": "",     # pdf docs get pdf_engine below
    "eval-pdf-hybrid": "",
}
PDF_ENGINE = {"eval-base": "pypdfium2", "eval-token": "pypdfium2",
              "eval-noheads": "pypdfium2", "eval-nooverlap": "pypdfium2",
              "eval-pairs": "pypdfium2", "eval-pdf-pypdf": "pypdf",
              "eval-pdf-hybrid": "hybrid"}

# search-side ablations, run against eval-base only
SEARCH_VARIANTS: dict[str, dict] = {
    "hybrid": {"mode": "hybrid"},
    "vector": {"mode": "vector"},
    "lexical": {"mode": "lexical"},
    "lexical+strip": {"mode": "lexical", "lexical_stopword_strip": True},
    "hybrid+strip": {"mode": "hybrid", "lexical_stopword_strip": True},
    "lexical-bm25": {"mode": "lexical", "lexical_backend": "bm25"},
    "hybrid-bm25": {"mode": "hybrid", "lexical_backend": "bm25"},
    "hybrid-bm25-w03": {"mode": "hybrid", "lexical_backend": "bm25",
                        "vector_weight": 0.3},
}


def post_json(url: str, path: str, payload: dict, tenant: str) -> dict:
    request = urllib.request.Request(
        f"{url.rstrip('/')}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-tenant-slug": tenant})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())


def post_file(url: str, path: Path, params: str, tenant: str) -> dict:
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; '
               f'filename="{path.name}"\r\n'.encode())
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    body.write(path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{url.rstrip('/')}/ingest?include_text=false{params}",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "x-tenant-slug": tenant})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def ingest_corpus(ingest_url: str, api_url: str, corpus: Path,
                  tenant: str, params: str, pdf_engine: str) -> int:
    post_json(api_url, "/internal/tenants", {"slug": tenant}, tenant)
    chunks = 0
    for path in sorted(corpus.iterdir()):
        extra = params
        if path.suffix == ".pdf":
            extra += f"&pdf_engine={pdf_engine}"
        response = post_file(ingest_url, path, extra, tenant)
        chunks += response["n_chunks"]
    return chunks


def score_queries(api_url: str, tenant: str, queries: list[dict],
                  variant: dict, k: int = 8) -> list[dict]:
    rows = []
    for q in queries:
        payload = {"query": q["query"], "k": k, **variant}
        response = post_json(api_url, "/search", payload, tenant)
        rank = None
        for position, hit in enumerate(response["hits"], start=1):
            if q["expect_marker"].lower() in hit["content"].lower():
                rank = position
                break
        rows.append({**q, "rank": rank})
    return rows


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    ranks = [r["rank"] for r in rows]
    return {
        "n": n,
        "recall@1": round(sum(1 for r in ranks if r == 1) / n, 3),
        "recall@3": round(sum(1 for r in ranks if r and r <= 3) / n, 3),
        "recall@8": round(sum(1 for r in ranks if r and r <= 8) / n, 3),
        "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
    }


def run(ingest_url: str, api_url: str, corpus: Path,
        queries_path: Path, out_path: str | None,
        search_only: bool = False) -> None:
    queries = json.loads(queries_path.read_text())
    results: dict = {"configs": {}, "search_variants": {}, "per_class": {}}

    for tenant, params in ({} if search_only else INGEST_CONFIGS).items():
        t0 = time.time()
        chunks = ingest_corpus(ingest_url, api_url, corpus, tenant,
                               params, PDF_ENGINE[tenant])
        rows = score_queries(api_url, tenant, queries, {"mode": "hybrid"})
        agg = aggregate(rows)
        results["configs"][tenant] = {
            "chunks": chunks, "ingest_s": round(time.time() - t0, 1),
            **agg,
            "rows": rows}
        print(f"  {tenant:>16}: {chunks} chunks, r@3 {agg['recall@3']}, "
              f"mrr {agg['mrr']}")

    for name, variant in SEARCH_VARIANTS.items():
        rows = score_queries(api_url, "eval-base", queries, variant)
        agg = aggregate(rows)
        results["search_variants"][name] = {**agg, "rows": rows}
        print(f"  base/{name:>14}: r@3 {agg['recall@3']}, mrr {agg['mrr']}")

    if not search_only:
        classes = sorted({q["class"] for q in queries})
        base_rows = results["configs"]["eval-base"]["rows"]
        for cls in classes:
            results["per_class"][cls] = aggregate(
                [r for r in base_rows if r["class"] == cls])

    if out_path:
        Path(out_path).write_text(json.dumps(results, indent=1))
        print(f"\nwrote {out_path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ingest-url", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--corpus", default="eval/corpus")
    p.add_argument("--queries", default="eval/queries.json")
    p.add_argument("--json", default=None)
    p.add_argument("--search-only", action="store_true")
    a = p.parse_args()
    run(a.ingest_url, a.api_url, Path(a.corpus), Path(a.queries), a.json,
        search_only=a.search_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
