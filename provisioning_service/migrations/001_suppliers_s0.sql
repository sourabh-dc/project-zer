-- ═══════════════════════════════════════════════════════════════════
-- ZeroQue Suppliers — S0: Identity & Lifecycle
-- Run manually against the provisioning Postgres database.
-- Idempotent — safe to re-run.
-- ═══════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Legal organisations (platform-scoped real companies) ────────
CREATE TABLE IF NOT EXISTS legal_organisations (
    legal_org_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name             VARCHAR(255) NOT NULL,
    registration_number    VARCHAR(100),
    registration_authority VARCHAR(100),          -- e.g. companies_house
    country_code           VARCHAR(2),
    screening_status       VARCHAR(30) NOT NULL DEFAULT 'pending',  -- pending | clear | flagged
    screening_facts        JSONB,                 -- reg / screening evidence
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by             UUID REFERENCES users(user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_legal_orgs_reg
    ON legal_organisations (registration_authority, registration_number)
    WHERE registration_number IS NOT NULL;

-- ── 2. Link tenants → legal organisation ───────────────────────────
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS legal_org_id UUID
    REFERENCES legal_organisations(legal_org_id) ON DELETE SET NULL;

-- ── 3. Supplier profiles (one per supplier org tenant) ─────────────
CREATE TABLE IF NOT EXISTS supplier_profiles (
    supplier_profile_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL UNIQUE REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    legal_org_id        UUID REFERENCES legal_organisations(legal_org_id) ON DELETE SET NULL,
    trading_name        VARCHAR(255),
    lifecycle_status    VARCHAR(30) NOT NULL DEFAULT 'draft',  -- draft | submitted | approved | suspended
    contact_email       VARCHAR(255),
    connectivity        JSONB,                -- protocol / api / cxml / edi / webhook profile
    submitted_at        TIMESTAMPTZ,
    approved_at         TIMESTAMPTZ,
    approved_by         UUID REFERENCES users(user_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          UUID REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS ix_supplier_profiles_lifecycle
    ON supplier_profiles (lifecycle_status);

-- ── 4. Platform-ops permissions ────────────────────────────────────
INSERT INTO permissions (permission_id, code, description) VALUES
    (gen_random_uuid(), 'legal_orgs.manage',  'Manage legal organisations (platform ops)'),
    (gen_random_uuid(), 'suppliers.manage',   'Create and manage supplier organisations'),
    (gen_random_uuid(), 'suppliers.approve',  'Approve or suspend supplier organisations')
ON CONFLICT (code) DO NOTHING;

-- ── 5. Supplier-side permissions (used by supplier roles) ──────────
INSERT INTO permissions (permission_id, code, description) VALUES
    (gen_random_uuid(), 'suppliers.profile.manage',   'Manage own supplier profile and connectivity'),
    (gen_random_uuid(), 'suppliers.users.manage',     'Invite and manage users on the supplier org'),
    (gen_random_uuid(), 'catalogue.listings.manage',  'Manage supplier product listings and list prices'),
    (gen_random_uuid(), 'supplier_orders.manage',     'View and action supplier order inbox (ack / ship)'),
    (gen_random_uuid(), 'supplier_invoices.manage',   'Manage invoice metadata on supplier orders')
ON CONFLICT (code) DO NOTHING;

-- ── 6. Supplier roles ──────────────────────────────────────────────
INSERT INTO roles (role_id, code, description) VALUES
    (gen_random_uuid(), 'supplier_admin',     'Supplier admin — org, users, connectivity'),
    (gen_random_uuid(), 'catalogue_manager',  'Catalogue manager — listings, media, list prices'),
    (gen_random_uuid(), 'fulfilment',         'Fulfilment — order inbox, ack, ship'),
    (gen_random_uuid(), 'finance',            'Finance — invoice metadata (no payment rails)')
ON CONFLICT (code) DO NOTHING;

-- ── 7. Role → permission mappings ──────────────────────────────────
INSERT INTO role_permissions (id, role_code, permission_code)
SELECT gen_random_uuid(), r.role_code, r.permission_code
FROM (VALUES
    ('supplier_admin',    'suppliers.profile.manage'),
    ('supplier_admin',    'suppliers.users.manage'),
    ('supplier_admin',    'catalogue.listings.manage'),
    ('supplier_admin',    'supplier_orders.manage'),
    ('supplier_admin',    'supplier_invoices.manage'),
    ('supplier_admin',    'audit.view'),
    ('catalogue_manager', 'catalogue.listings.manage'),
    ('fulfilment',        'supplier_orders.manage'),
    ('finance',           'supplier_invoices.manage')
) AS r(role_code, permission_code)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permissions rp
    WHERE rp.role_code = r.role_code AND rp.permission_code = r.permission_code
);

COMMIT;
