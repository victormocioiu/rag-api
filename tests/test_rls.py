"""The multi-tenant enforcement, asserted.

RLS with FORCE means: tenant B cannot see tenant A's rows, and a connection
with NO tenant context sees zero rows -- fail-closed, even for the table
owner. If any of these tests fail, multi-tenancy is decorative."""

import pytest
from conftest import CHUNKS_A, DATABASE_URL, vec

from rag_api.db import resolve_tenant, tenant_transaction
from rag_api.repositories import persist_document, search

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="TEST_DATABASE_URL not set")

HASH_A = "a" * 64


async def two_tenants(pool) -> tuple[str, str]:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenants (slug, name) VALUES ('acme', 'Acme') "
            "ON CONFLICT (slug) DO NOTHING")
    tenant_a = await resolve_tenant(pool, "default")
    tenant_b = await resolve_tenant(pool, "acme")
    assert tenant_a and tenant_b
    return tenant_a, tenant_b


async def test_tenant_b_sees_nothing_of_tenant_a(pool):
    tenant_a, tenant_b = await two_tenants(pool)
    await persist_document(
        pool, tenant_a, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)

    async with tenant_transaction(pool, tenant_b) as conn:
        assert await conn.fetchval("SELECT count(*) FROM documents") == 0
        assert await conn.fetchval("SELECT count(*) FROM chunks") == 0

    hits = await search(pool, tenant_b, query_embedding=vec(0),
                        query_text="refund policy", mode="hybrid", k=8)
    assert hits == []


async def test_no_tenant_context_fails_closed(pool):
    tenant_a, _ = await two_tenants(pool)
    await persist_document(
        pool, tenant_a, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)

    # a plain pooled connection, no app.tenant_id set: zero rows, not an error
    assert await pool.fetchval("SELECT count(*) FROM documents") == 0
    assert await pool.fetchval("SELECT count(*) FROM chunks") == 0


async def test_cannot_insert_for_another_tenant(pool):
    tenant_a, tenant_b = await two_tenants(pool)
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_transaction(pool, tenant_b) as conn:
            await conn.execute(
                """INSERT INTO documents (tenant_id, content_hash, mime_type)
                   VALUES ($1, $2, 'text/plain')""",
                tenant_a, b"\x01" * 32)
