"""Pool, migration runner, and the tenant context.

The migration runner is deliberately boring: numbered .sql files applied in
order, tracked in schema_migrations, each in a transaction. The SQL stays
visible and greppable -- the schema IS the documentation.

tenant_transaction() is the only way the app touches tenant-scoped tables:
it opens a transaction and sets app.tenant_id with SET LOCAL, which the RLS
policies read. Outside a tenant transaction, the policies fail closed and
tenant-scoped tables return zero rows.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(database_url, min_size=1, max_size=8)


async def run_migrations(pool: asyncpg.Pool,
                         directory: Path = MIGRATIONS_DIR) -> list[str]:
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        done = {r["filename"] for r in
                await conn.fetch("SELECT filename FROM schema_migrations")}
        for path in sorted(directory.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)",
                    path.name)
            applied.append(path.name)
    return applied


@contextlib.asynccontextmanager
async def tenant_transaction(pool: asyncpg.Pool,
                             tenant_id: str) -> AsyncIterator[asyncpg.Connection]:
    """A transaction with the RLS tenant context set. SET LOCAL scopes the
    setting to this transaction only -- nothing leaks to the pooled
    connection's next user."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "SELECT set_config('app.tenant_id', $1, true)", tenant_id)
        yield conn


async def resolve_tenant(pool: asyncpg.Pool, slug: str) -> str | None:
    row = await pool.fetchrow("SELECT id FROM tenants WHERE slug = $1", slug)
    return str(row["id"]) if row else None
