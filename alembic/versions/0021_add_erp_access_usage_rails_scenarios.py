"""add_erp_access_usage_rails_scenarios_tables

Revision ID: 3601a86a8f37
Revises: 67a07f48bea6
Create Date: 2025-10-01 04:58:31.744771+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3601a86a8f37'
down_revision = '67a07f48bea6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create scenarios table first (referenced by tenants)
    op.execute("""
    CREATE TABLE scenarios (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        code VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(100) NOT NULL,
        config JSONB NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    
    # Add scenario_id to tenants table
    op.execute("""
    ALTER TABLE tenants ADD COLUMN scenario_id UUID NULL REFERENCES scenarios(id) ON DELETE SET NULL;
    """)
    
    # Create erp_integrations table
    op.execute("""
    CREATE TABLE erp_integrations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id VARCHAR(255) NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
        vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
        type VARCHAR(20) NOT NULL CHECK (type IN ('ERP', 'CRM')),
        config JSONB NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        last_sync_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NULL,
        CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL))
    );
    """)
    
    # Create access_controls table
    op.execute("""
    CREATE TABLE access_controls (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        site_id VARCHAR(255) NULL REFERENCES sites(site_id) ON DELETE CASCADE,
        store_id VARCHAR(255) NULL REFERENCES stores(store_id) ON DELETE CASCADE,
        type VARCHAR(20) NOT NULL CHECK (type IN ('gate', 'RFID', 'lock', 'card_reader')),
        config JSONB NOT NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NULL,
        CHECK ((site_id IS NOT NULL) OR (store_id IS NOT NULL))
    );
    """)
    
    # Create user_access_grants table
    op.execute("""
    CREATE TABLE user_access_grants (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        access_control_id UUID NOT NULL REFERENCES access_controls(id) ON DELETE CASCADE,
        grant_type VARCHAR(20) NOT NULL DEFAULT 'permanent',
        valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        valid_until TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    
    # Create usage_ledger_entries table
    op.execute("""
    CREATE TABLE usage_ledger_entries (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id VARCHAR(255) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
        site_id VARCHAR(255) NULL REFERENCES sites(site_id) ON DELETE SET NULL,
        store_id VARCHAR(255) NULL REFERENCES stores(store_id) ON DELETE SET NULL,
        meter_code VARCHAR(100) NOT NULL REFERENCES usage_meters(code),
        value BIGINT NOT NULL DEFAULT 1,
        billed_at TIMESTAMPTZ NULL,
        reference_id UUID NULL,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    
    # Create zeroque_rails table
    op.execute("""
    CREATE TABLE zeroque_rails (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        type VARCHAR(20) NOT NULL CHECK (type IN ('payments', 'cv', 'marketplace')),
        config JSONB NOT NULL,
        active BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NULL
    );
    """)


def downgrade() -> None:
    # Drop tables in reverse order
    op.execute("DROP TABLE IF EXISTS zeroque_rails;")
    op.execute("DROP TABLE IF EXISTS usage_ledger_entries;")
    op.execute("DROP TABLE IF EXISTS user_access_grants;")
    op.execute("DROP TABLE IF EXISTS access_controls;")
    op.execute("DROP TABLE IF EXISTS erp_integrations;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS scenario_id;")
    op.execute("DROP TABLE IF EXISTS scenarios;")


