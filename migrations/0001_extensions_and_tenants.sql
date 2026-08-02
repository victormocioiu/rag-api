-- Extensions + the tenants table.
--
-- pgvector >= 0.8.0 is REQUIRED: iterative index scans are what stop a
-- post-filtered ANN scan from destroying recall for small tenants. Fail the
-- migration loudly rather than degrade silently.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

DO $$
DECLARE v text;
BEGIN
    SELECT extversion INTO v FROM pg_extension WHERE extname = 'vector';
    IF string_to_array(v, '.')::int[] < ARRAY[0,8,0] THEN
        RAISE EXCEPTION
          'pgvector % is too old; >= 0.8.0 required for hnsw.iterative_scan', v;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS tenants (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                text UNIQUE NOT NULL,
    name                text NOT NULL,
    settings            jsonb NOT NULL DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- A default tenant so the platform works before auth exists (part 4 wires
-- real tenancy through the gateway; the schema is multi-tenant from day one).
INSERT INTO tenants (slug, name)
VALUES ('default', 'Default tenant')
ON CONFLICT (slug) DO NOTHING;
