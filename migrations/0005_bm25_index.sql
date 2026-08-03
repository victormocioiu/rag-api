-- BM25 lexical arm (pg_textsearch). The extension arrives via CNPG's
-- declarative image-volume mechanism and is preloaded server-side; this
-- migration is a no-op on databases without it (local test pg), so the
-- tsquery arm remains the fallback everywhere.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions
               WHERE name = 'pg_textsearch') THEN
        CREATE EXTENSION IF NOT EXISTS pg_textsearch;
        -- text_config 'simple': no stemming, same language-neutral choice
        -- as the tsvector column (multilingual corpus invariant)
        CREATE INDEX IF NOT EXISTS chunks_content_bm25
            ON chunks USING bm25 (content) WITH (text_config = 'simple');
    END IF;
END $$;
