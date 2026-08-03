import pytest
from conftest import CHUNKS_A, DATABASE_URL, vec

from rag_api.db import resolve_tenant, run_migrations, tenant_transaction
from rag_api.repositories import persist_document, search

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="TEST_DATABASE_URL not set")

HASH_A = "a" * 64


async def test_migrations_are_idempotent(pool):
    applied_again = await run_migrations(pool)
    assert applied_again == []


async def test_default_tenant_seeded(pool):
    assert await resolve_tenant(pool, "default") is not None
    assert await resolve_tenant(pool, "nope") is None


async def test_persist_roundtrip_and_idempotency(pool):
    tenant = await resolve_tenant(pool, "default")
    first = await persist_document(
        pool, tenant, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)
    assert first.created and first.n_chunks == 2

    again = await persist_document(
        pool, tenant, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)
    assert not again.created
    assert again.document_id == first.document_id

    async with tenant_transaction(pool, tenant) as conn:
        status = await conn.fetchval(
            "SELECT status FROM documents WHERE id = $1", first.document_id)
        n = await conn.fetchval("SELECT count(*) FROM chunks")
    assert status == "ready"
    assert n == 2


async def test_vector_search_finds_nearest(pool):
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)
    hits = await search(pool, tenant, query_embedding=vec(1),
                        query_text="", mode="vector", k=2)
    assert hits[0].ordinal == 1  # nearest to vec(1)


async def test_lexical_search_matches_words(pool):
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)
    hits = await search(pool, tenant, query_embedding=None,
                        query_text="refund policy", mode="lexical", k=2)
    assert hits and hits[0].ordinal == 0
    assert hits[0].lexical_rank == 1


async def test_hybrid_fuses_both_signals(pool):
    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)
    # vector points at chunk 1, words point at chunk 0 -> both surface
    hits = await search(pool, tenant, query_embedding=vec(1),
                        query_text="refund policy", mode="hybrid", k=2)
    ordinals = {h.ordinal for h in hits}
    assert ordinals == {0, 1}


async def test_stopword_strip_rescues_natural_questions(pool):
    from rag_api.repositories import strip_stopwords

    assert strip_stopwords("what is the refund policy?") == "refund policy"
    assert strip_stopwords("the the the") == "the the the"  # never empty

    tenant = await resolve_tenant(pool, "default")
    await persist_document(
        pool, tenant, HASH_A, "doc.md", "text/markdown", 123, CHUNKS_A)
    natural = "what is the refund policy for returns?"
    plain = await search(pool, tenant, None, natural, mode="lexical", k=4)
    stripped = await search(pool, tenant, None, natural, mode="lexical", k=4,
                            lexical_stopword_strip=True)
    assert plain == []          # AND-of-stopwords matches nothing
    assert stripped             # stripped query finds the refund chunk
    assert stripped[0].ordinal == 0


async def test_persist_strips_nul_bytes(pool, tenant_a):
    """Postgres TEXT rejects \\x00; the persist boundary must sanitize --
    real corpora (EnterpriseRAG-Bench noise docs) contain them."""
    result = await persist_document(
        pool, tenant_a, "ab" * 32, "nul\x00doc.txt", "text/plain", 10,
        [{"index": 0, "text": "before\x00after", "n_tokens": 2,
          "heading_path": "h\x00p", "embedding": [0.1] * 384}])
    assert result.created
    hits = await search(pool, tenant, [0.1] * 384, "beforeafter", k=3)
    assert any("beforeafter" in h.content for h in hits)
