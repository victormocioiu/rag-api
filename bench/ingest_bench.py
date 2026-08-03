"""Ingest the EnterpriseRAG-Bench export through the live platform.

Async, resumable, honest: every document goes through the real pipeline
(rag-ingest -> rag-embedder -> rag-api -> Postgres) exactly like customer
traffic. The state file maps our document ids to the benchmark's dsid_
uuids -- the join key for scoring -- and doubles as the resume ledger:
files already present are skipped, and the platform's content-hash
idempotency makes accidental re-sends free.

    uv run --with httpx python bench/ingest_bench.py \\
        --export-dir ../EnterpriseRAG-Bench/export_data \\
        --ingest-url https://rag-ingest.<tailnet>.ts.net \\
        --api-url https://rag-api.<tailnet>.ts.net \\
        --tenant erb-v1 --concurrency 12 \\
        --state bench/state-erb-v1.jsonl [--limit 2000]
"""

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

import httpx

DSID_PREFIX = "dsid_"


def find_docs(export_dir: Path) -> list[Path]:
    docs = [p for p in export_dir.rglob("*.txt")
            if p.name.startswith(DSID_PREFIX)]
    docs.sort()
    return docs


def dsid_of(path: Path) -> str:
    return path.name.split("__", 1)[0]


async def ingest_one(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                     ingest_url: str, tenant: str, path: Path,
                     state_fh, lock: asyncio.Lock,
                     stats: dict) -> None:
    async with sem:
        t0 = time.monotonic()
        for attempt in range(4):
            try:
                response = await client.post(
                    f"{ingest_url}/ingest",
                    params={"include_text": "false"},
                    headers={"x-tenant-slug": tenant},
                    files={"file": (path.name, path.read_bytes(),
                                    "text/plain")})
                response.raise_for_status()
                break
            except (httpx.HTTPError, OSError) as exc:
                if attempt == 3:
                    async with lock:
                        stats["errors"] += 1
                        state_fh.write(json.dumps(
                            {"file": path.name, "error": str(exc)}) + "\n")
                        state_fh.flush()
                    return
                await asyncio.sleep(2 ** attempt)
        body = response.json()
        row = {
            "file": path.name,
            "dsid": dsid_of(path),
            "document_id": body.get("document_id"),
            "n_chunks": body["n_chunks"],
            "n_tokens": body["n_tokens_total"],
            "ms": round((time.monotonic() - t0) * 1000, 1),
        }
        async with lock:
            state_fh.write(json.dumps(row) + "\n")
            stats["docs"] += 1
            stats["chunks"] += row["n_chunks"]
            stats["tokens"] += row["n_tokens"]
            if stats["docs"] % 500 == 0:
                dt = time.monotonic() - stats["t0"]
                print(f"  {stats['docs']:>7} docs  {stats['chunks']:>8} chunks "
                      f"{stats['tokens'] / 1e6:>7.2f}M tok  "
                      f"{stats['docs'] / dt:>6.1f} docs/s  "
                      f"{stats['tokens'] / dt / 1000:>6.1f}k tok/s  "
                      f"errors {stats['errors']}", flush=True)
                state_fh.flush()


async def run(args) -> None:
    export_dir = Path(args.export_dir)
    docs = find_docs(export_dir)
    print(f"{len(docs)} documents in {export_dir}")

    done: set[str] = set()
    state_path = Path(args.state)
    if state_path.exists():
        for line in state_path.read_text().splitlines():
            row = json.loads(line)
            if "error" not in row:
                done.add(row["file"])
        print(f"resume: {len(done)} already ingested")
    todo = [p for p in docs if p.name not in done]
    if args.limit:
        # spread the sample across all sources, deterministically
        random.Random(42).shuffle(todo)
        todo = todo[:args.limit]
    print(f"{len(todo)} to ingest, concurrency {args.concurrency}")

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{args.api_url}/internal/tenants", json={"slug": args.tenant})
        response.raise_for_status()

        sem = asyncio.Semaphore(args.concurrency)
        lock = asyncio.Lock()
        stats = {"docs": 0, "chunks": 0, "tokens": 0, "errors": 0,
                 "t0": time.monotonic()}
        # blocking open is fine: local appends measured in microseconds,
        # and the ledger must flush eagerly to survive a killed run
        with state_path.open("a") as state_fh:  # noqa: ASYNC230
            await asyncio.gather(*(
                ingest_one(client, sem, args.ingest_url, args.tenant,
                           path, state_fh, lock, stats)
                for path in todo))

    dt = time.monotonic() - stats["t0"]
    print(f"\ndone: {stats['docs']} docs, {stats['chunks']} chunks, "
          f"{stats['tokens'] / 1e6:.2f}M tokens in {dt / 60:.1f} min "
          f"({stats['docs'] / dt:.1f} docs/s, "
          f"{stats['tokens'] / dt / 1000:.1f}k tok/s), "
          f"{stats['errors']} errors")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--export-dir", required=True)
    p.add_argument("--ingest-url", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--tenant", default="erb-v1")
    p.add_argument("--concurrency", type=int, default=12)
    p.add_argument("--state", default="bench/state.jsonl")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
