-- BM25 lexical arm (pg_textsearch). Layering matters here:
--   1. the BINARY arrives via CNPG's declarative image-volume extensions
--      (cluster spec) + shared_preload_libraries
--   2. CREATE EXTENSION requires superuser (pg_textsearch is untrusted),
--      so it belongs to cluster provisioning -- CNPG's Database CR
--      `spec.extensions` or a one-off as postgres -- NOT to app
--      migrations, which run as the non-superuser app role
--   3. this migration only builds the index, and only where step 2
--      already happened; everywhere else (local test pg, clusters
--      without the extension) it is a no-op and the tsquery arm serves
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_textsearch')
    THEN
        CREATE INDEX IF NOT EXISTS chunks_content_bm25
            ON chunks USING bm25 (content) WITH (text_config = 'simple');
    END IF;
END $$;
