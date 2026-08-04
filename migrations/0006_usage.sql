-- Per-tenant daily usage counters. One row per tenant per day, upserted
-- on every chat -- coarse by design: the goal is budget enforcement and
-- a usage endpoint, not billing-grade accounting. Token numbers are
-- chars/4 estimates recorded at request time.
CREATE TABLE IF NOT EXISTS usage_daily (
    tenant_id  uuid NOT NULL REFERENCES tenants(id),
    day        date NOT NULL DEFAULT current_date,
    chats      bigint NOT NULL DEFAULT 0,
    llm_tokens_in  bigint NOT NULL DEFAULT 0,
    llm_tokens_out bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, day)
);
ALTER TABLE usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS usage_tenant_isolation ON usage_daily;
CREATE POLICY usage_tenant_isolation ON usage_daily
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
