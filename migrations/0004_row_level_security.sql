-- Row-level security: the multi-tenant enforcement.
--
-- FORCE is the load-bearing word. Without it the table OWNER -- which is
-- exactly the role the app connects as -- bypasses every policy silently,
-- and RLS becomes decorative.
--
-- The tenant context read is wrapped in NULLIF(..., ''): a never-set GUC
-- reads as NULL, but a POOLED CONNECTION that previously ran a tenant
-- transaction reverts the GUC to the EMPTY STRING after commit -- and
-- ''::uuid is a cast error, not a filter. NULLIF maps both states to NULL,
-- NULL fails the comparison, and either way an absent tenant context yields
-- ZERO rows. Fail-closed by construction; tests/test_rls.py asserts it.

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE  ROW LEVEL SECURITY;
ALTER TABLE chunks    ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks    FORCE  ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE tablename = 'documents' AND policyname = 'tenant_isolation') THEN
        CREATE POLICY tenant_isolation ON documents
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE tablename = 'chunks' AND policyname = 'tenant_isolation') THEN
        CREATE POLICY tenant_isolation ON chunks
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    END IF;
END $$;
