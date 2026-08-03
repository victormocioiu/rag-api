"""All SQL against tenant-scoped tables lives here, and every call runs
inside tenant_transaction() -- RLS is the enforcement, this layer is the
convention that keeps it auditable."""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from rag_api.db import tenant_transaction

RRF_K = 60  # reciprocal-rank-fusion constant; standard, insensitive

# The 'simple' tsvector config keeps stopwords, and websearch ANDs terms --
# so natural-language questions demand "how" AND "long" AND "is" to appear.
# Stripping stopwords from the QUERY (not the index) is the cheap fix; the
# eval measures whether it helps. English-only list: the index config is
# language-agnostic, the queries in the eval are English.
STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "how", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "this", "to", "was", "what", "when", "where", "which", "who", "why",
    "will", "with", "does", "do", "did",
])


def strip_stopwords(query: str) -> str:
    kept = [w.strip("?.,!") for w in query.split()
            if w.lower().strip("?.,!") not in STOPWORDS]
    kept = [w for w in kept if w]
    return " ".join(kept) if kept else query


def _vec(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def _pg_text(s: str) -> str:
    # Postgres TEXT rejects NUL (CharacterNotInRepertoireError); real
    # corpora contain them and the DB boundary is where they must die
    return s.replace("\x00", "")


@dataclass
class PersistResult:
    document_id: str
    created: bool
    n_chunks: int


async def persist_document(
    pool: asyncpg.Pool,
    tenant_id: str,
    content_hash_hex: str,
    filename: str,
    mime_type: str,
    byte_size: int,
    chunks: list[dict],
) -> PersistResult:
    """One transaction per document: insert doc + all chunks, then flip
    status to ready. Idempotent on (tenant_id, content_hash): re-posting an
    existing document is a no-op that returns the existing id."""
    content_hash = bytes.fromhex(content_hash_hex)
    async with tenant_transaction(pool, tenant_id) as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM documents WHERE tenant_id = $1 AND content_hash = $2",
            tenant_id, content_hash)
        if existing:
            return PersistResult(str(existing["id"]), created=False,
                                 n_chunks=0)
        doc = await conn.fetchrow(
            """INSERT INTO documents
                   (tenant_id, content_hash, filename, mime_type, byte_size)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            tenant_id, content_hash, _pg_text(filename), mime_type,
            byte_size)
        document_id = doc["id"]
        await conn.executemany(
            """INSERT INTO chunks (tenant_id, document_id, ordinal, content,
                                   token_count, heading_path, page, embedding)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::halfvec)""",
            [(tenant_id, document_id, c["index"], _pg_text(c["text"]),
              c["n_tokens"], _pg_text(c.get("heading_path", "")),
              c.get("page"), _vec(c["embedding"]))
             for c in chunks])
        await conn.execute(
            "UPDATE documents SET status = 'ready', updated_at = now() "
            "WHERE id = $1", document_id)
        return PersistResult(str(document_id), created=True,
                             n_chunks=len(chunks))


@dataclass
class SearchHit:
    chunk_id: int
    document_id: str
    ordinal: int
    content: str
    heading_path: str
    page: int | None
    score: float
    vector_rank: int | None = None
    lexical_rank: int | None = None


async def search(
    pool: asyncpg.Pool,
    tenant_id: str,
    query_embedding: list[float] | None,
    query_text: str,
    k: int = 8,
    mode: str = "hybrid",
    candidates: int = 50,
    lexical_stopword_strip: bool = False,
    lexical_backend: str = "tsquery",
    vector_weight: float = 1.0,
) -> list[SearchHit]:
    """Hybrid = vector KNN + full-text, fused with reciprocal-rank fusion.
    Both halves run in the same tenant transaction; RLS scopes both."""
    async with tenant_transaction(pool, tenant_id) as conn:
        vector_rows: list[asyncpg.Record] = []
        lexical_rows: list[asyncpg.Record] = []
        if mode in ("hybrid", "vector") and query_embedding is not None:
            vector_rows = await conn.fetch(
                """SELECT id, document_id, ordinal, content, heading_path, page
                   FROM chunks
                   ORDER BY embedding <#> $1::halfvec
                   LIMIT $2""",
                _vec(query_embedding), candidates)
        if mode in ("hybrid", "lexical"):
            lexical_query = (strip_stopwords(query_text)
                             if lexical_stopword_strip else query_text)
            if lexical_backend == "bm25":
                # pg_textsearch: OR-with-IDF ranking, Block-Max WAND top-k.
                # <@> returns the NEGATIVE bm25 score (index scans are ASC).
                # to_bm25query is required with a parameter: bare
                # `content <@> $1` cannot auto-detect the index at plan time
                lexical_rows = await conn.fetch(
                    """SELECT id, document_id, ordinal, content, heading_path,
                              page
                       FROM chunks
                       ORDER BY content <@>
                                to_bm25query($1, 'chunks_content_bm25')
                       LIMIT $2""",
                    lexical_query, candidates)
            else:
                lexical_rows = await conn.fetch(
                    """SELECT id, document_id, ordinal, content, heading_path,
                              page
                       FROM chunks,
                            websearch_to_tsquery('simple', $1) AS q
                       WHERE content_tsv @@ q
                       ORDER BY ts_rank_cd(content_tsv, q) DESC
                       LIMIT $2""",
                    lexical_query, candidates)

    # vector_weight scales the vector arm's RRF contribution: with arms of
    # very different solo quality, equal-weight fusion lets the weak arm
    # dilute the strong one (measured on ERB: 0.62 equal vs 0.67 at 0.3)
    hits: dict[int, SearchHit] = {}
    for rank, row in enumerate(vector_rows, start=1):
        hits[row["id"]] = SearchHit(
            chunk_id=row["id"], document_id=str(row["document_id"]),
            ordinal=row["ordinal"], content=row["content"],
            heading_path=row["heading_path"], page=row["page"],
            score=vector_weight / (RRF_K + rank), vector_rank=rank)
    for rank, row in enumerate(lexical_rows, start=1):
        if row["id"] in hits:
            hits[row["id"]].score += 1.0 / (RRF_K + rank)
            hits[row["id"]].lexical_rank = rank
        else:
            hits[row["id"]] = SearchHit(
                chunk_id=row["id"], document_id=str(row["document_id"]),
                ordinal=row["ordinal"], content=row["content"],
                heading_path=row["heading_path"], page=row["page"],
                score=1.0 / (RRF_K + rank), lexical_rank=rank)
    return sorted(hits.values(), key=lambda h: h.score, reverse=True)[:k]
