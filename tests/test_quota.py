"""Token-page accounting. A "page" is n_tokens/page_tokens rounded up,
never the file format's own page numbers -- one huge single-page .txt
must count as many pages, or the 20-page limit means nothing."""

import pytest
from conftest import CHUNKS_A, DATABASE_URL, vec

from rag_api.db import resolve_tenant
from rag_api.repositories import (
    count_documents,
    persist_document,
    tenant_usage,
)

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="TEST_DATABASE_URL not set")


def chunk(index: int, n_tokens: int) -> dict:
    return {"index": index, "text": f"filler {index}", "n_tokens": n_tokens,
            "heading_path": "", "page": None, "embedding": vec(index)}


async def test_huge_text_counts_many_pages(pool):
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, "b" * 64, "huge.txt", "text/plain", 1,
        [chunk(0, 12_000), chunk(1, 12_000)])
    usage = await tenant_usage(pool, tenant, page_tokens=500)
    assert usage["pages"] == 48  # ceil(24000 / 500), not "1 page of txt"


async def test_small_doc_is_at_least_one_page(pool):
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, "a" * 64, "doc.md", "text/markdown", 1, CHUNKS_A)
    usage = await tenant_usage(pool, tenant, page_tokens=500)
    assert usage["pages"] == 1  # 18 tokens rounds up to one page, not zero


async def test_pages_sum_per_document(pool):
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, "a" * 64, "doc.md", "text/markdown", 1, CHUNKS_A)
    await persist_document(
        pool, tenant, "c" * 64, "big.txt", "text/plain", 1,
        [chunk(0, 700)])
    usage = await tenant_usage(pool, tenant, page_tokens=500)
    assert usage["pages"] == 1 + 2
    assert await count_documents(pool, tenant) == 2
