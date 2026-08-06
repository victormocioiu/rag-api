-- First-party analytics. Not tenant-scoped: visits happen before tenants
-- exist. Written only through /internal/events (the UI's server routes);
-- IP and UA are stored raw for audience analysis -- surface a privacy
-- note wherever this is deployed publicly.
CREATE TABLE IF NOT EXISTS analytics_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    event       text NOT NULL,
    path        text NOT NULL DEFAULT '',
    ip          inet,
    user_agent  text NOT NULL DEFAULT '',
    language    text NOT NULL DEFAULT '',
    referrer    text NOT NULL DEFAULT '',
    country     text,
    user_hash   text,
    tenant_slug text,
    props       jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS analytics_events_at   ON analytics_events (at);
CREATE INDEX IF NOT EXISTS analytics_events_event ON analytics_events (event, at);
