-- Migration 001: Derived Knowledge table
-- Run this on staging/production databases.
-- Locally, store.ensure_table_exists() handles this automatically at startup.

CREATE TABLE IF NOT EXISTS derived_knowledge (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL,
    fact_type   VARCHAR(100) NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    version     INTEGER NOT NULL DEFAULT 1,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookup by tenant + fact type (the read path)
CREATE INDEX IF NOT EXISTS idx_derived_tenant_type
    ON derived_knowledge (tenant_id, fact_type);

-- Index for version ordering within a tenant+type
CREATE INDEX IF NOT EXISTS idx_derived_tenant_type_version
    ON derived_knowledge (tenant_id, fact_type, version DESC);

COMMENT ON TABLE derived_knowledge IS
    'Precomputed business facts for the intelligence layer. '
    'Versioned — each recomputation adds a new row. Old rows kept for audit. '
    'Read: SELECT ... ORDER BY version DESC LIMIT 1. '
    'Write: INSERT with version = MAX(version) + 1.';
