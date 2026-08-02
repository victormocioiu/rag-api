"""Integration tests against a REAL postgres with pgvector.

    docker run -d --rm -p 5433:5432 -e POSTGRES_PASSWORD=test \\
        --name ragpg pgvector/pgvector:pg17
    TEST_DATABASE_URL=postgresql://postgres:test@localhost:5433/postgres \\
        uv run pytest -v

Skipped entirely when TEST_DATABASE_URL is unset. CI runs them against a
pgvector service container.
"""

import os

import asyncpg
import pytest

from rag_api.db import run_migrations

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None, reason="TEST_DATABASE_URL not set")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def pool():
    """A pool connected as a NON-SUPERUSER owner role, mirroring production
    (CNPG's `app` user owns the schema but is not superuser).

    This is load-bearing: superusers bypass RLS entirely -- FORCE or not --
    so isolation tests that connect as `postgres` prove nothing. Our first
    run made exactly that mistake; the failing tests caught it.
    """
    assert DATABASE_URL is not None
    admin = await asyncpg.connect(DATABASE_URL)
    await admin.execute("DROP SCHEMA public CASCADE")
    await admin.execute("CREATE SCHEMA public")
    await admin.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'appuser') THEN
                CREATE ROLE appuser LOGIN PASSWORD 'appuser' NOSUPERUSER;
            END IF;
        END $$;
    """)
    await admin.execute("GRANT ALL ON SCHEMA public TO appuser")
    # extensions need superuser in vanilla postgres; in the cluster the
    # CNPG operator owns this step. Migrations' IF NOT EXISTS then no-op.
    await admin.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await admin.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    await admin.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    await admin.close()

    app_url = DATABASE_URL.replace("postgres:test@", "appuser:appuser@")
    pool = await asyncpg.create_pool(app_url, min_size=1, max_size=4)
    await run_migrations(pool)  # tables owned by the non-superuser role
    yield pool
    await pool.close()


def vec(hot: int) -> list[float]:
    """A deterministic unit vector: 1.0 in one dimension."""
    v = [0.0] * 384
    v[hot % 384] = 1.0
    return v


CHUNKS_A = [
    {"index": 0, "text": "The refund policy allows returns within thirty days.",
     "n_tokens": 10, "heading_path": "Billing > Refunds", "page": None,
     "embedding": vec(0)},
    {"index": 1, "text": "Quarterly onboarding numbers grew steadily.",
     "n_tokens": 8, "heading_path": "Reports", "page": None,
     "embedding": vec(1)},
]
