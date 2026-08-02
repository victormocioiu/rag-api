-- HNSW + GIN: the two indexes that make hybrid search one database.
--
-- halfvec_ip_ops (inner product), not cosine: the embedder L2-normalizes
-- every vector, so IP ranks identically to cosine and is cheaper. This is
-- why "norm 1.0" has been an invariant since the embedder's first commit.
--
-- m=16 / ef_construction=64 are pgvector defaults and the right start;
-- raise ef_construction only if measured recall falls short (eval decides).
--
-- For bulk backfills: build HNSW AFTER the load (incremental insertion into
-- HNSW during a large backfill is dramatically slower than one build).

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks
    USING hnsw (embedding halfvec_ip_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING gin (content_tsv);

CREATE INDEX IF NOT EXISTS chunks_tenant_doc ON chunks (tenant_id, document_id);
CREATE INDEX IF NOT EXISTS documents_tenant_status ON documents (tenant_id, status);
