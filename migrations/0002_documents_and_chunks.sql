-- Documents and chunks: the memory of the pipeline.
--
-- halfvec(384): half the index and heap footprint of vector(384), with recall
-- loss that is negligible at these dimensions. 384 * 2 bytes = 768 bytes per
-- embedding.
--
-- content_tsv uses 'simple' -- no stemming, no stopwords. The only correct
-- choice when tenants upload documents in languages we do not know: stemming
-- in the wrong language is worse than none. This column is the lexical half
-- of hybrid search, maintained by Postgres itself (GENERATED ALWAYS).

CREATE TABLE IF NOT EXISTS documents (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    content_hash  bytea NOT NULL,
    filename      text NOT NULL DEFAULT '',
    mime_type     text NOT NULL,
    byte_size     bigint NOT NULL DEFAULT 0,
    status        text NOT NULL DEFAULT 'pending',
    error         text,
    metadata      jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, content_hash)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            bigserial PRIMARY KEY,
    tenant_id     uuid NOT NULL,
    document_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       int NOT NULL,
    content       text NOT NULL,
    token_count   int NOT NULL,
    heading_path  text NOT NULL DEFAULT '',
    page          int,
    embedding     halfvec(384) NOT NULL,
    content_tsv   tsvector GENERATED ALWAYS AS
                      (to_tsvector('simple', content)) STORED,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, ordinal)
);
