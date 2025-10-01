"""add_missing_v4_1_tables

Revision ID: 67a07f48bea6
Revises: 62f0c0cc1f1f
Create Date: 2025-09-30 15:18:32.904376+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '67a07f48bea6'
down_revision = '62f0c0cc1f1f'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create product_tax_categories table
    op.execute("""
    CREATE TABLE product_tax_categories (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        product_id UUID NOT NULL REFERENCES product_master(product_id) ON DELETE CASCADE,
        region_id UUID NOT NULL REFERENCES tax_regions(region_id) ON DELETE CASCADE,
        tax_category VARCHAR(100) NOT NULL,
        effective_from DATE NOT NULL,
        effective_until DATE NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(product_id, region_id, effective_from)
    );
    """)
    
    # Create pricing_versions table
    op.execute("""
    CREATE TABLE pricing_versions (
        version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        version_type VARCHAR(50) NOT NULL,
        version_number BIGINT NOT NULL,
        description TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(version_type, version_number)
    );
    """)
    
    # Create returns table
    op.execute("""
    CREATE TABLE returns (
        return_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        order_item_id INTEGER NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        reason VARCHAR(100) NOT NULL,
        condition VARCHAR(20) NOT NULL DEFAULT 'unopened',
        state VARCHAR(20) NOT NULL DEFAULT 'requested',
        refund_amount_minor BIGINT NULL,
        restocking_fee_minor BIGINT NOT NULL DEFAULT 0,
        processed_by VARCHAR(255) NULL REFERENCES users(user_id),
        processed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NULL
    );
    """)
    
    # Create refunds table
    op.execute("""
    CREATE TABLE refunds (
        refund_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        order_id INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
        amount_minor BIGINT NOT NULL,
        currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
        reason VARCHAR(100) NOT NULL,
        provider_ref VARCHAR(200) NULL,
        state VARCHAR(20) NOT NULL DEFAULT 'pending',
        processed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    
    # Create vendor_settlement_batches table
    op.execute("""
    CREATE TABLE vendor_settlement_batches (
        batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        period_start TIMESTAMPTZ NOT NULL,
        period_end TIMESTAMPTZ NOT NULL,
        currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
        total_payout_minor BIGINT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'processing',
        processed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    
    # Create vendor_settlement_items table
    op.execute("""
    CREATE TABLE vendor_settlement_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        batch_id UUID NOT NULL REFERENCES vendor_settlement_batches(batch_id) ON DELETE CASCADE,
        settlement_id UUID NOT NULL REFERENCES vendor_settlements(settlement_id) ON DELETE CASCADE,
        vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
        payout_amount_minor BIGINT NOT NULL,
        commission_amount_minor BIGINT NOT NULL,
        fee_amount_minor BIGINT NOT NULL DEFAULT 0,
        net_amount_minor BIGINT NOT NULL,
        settlement_status payout_status NOT NULL DEFAULT 'pending',
        paid_out_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)
    
    # Create vendor_settlement_adjustments table
    op.execute("""
    CREATE TABLE vendor_settlement_adjustments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
        adjustment_type VARCHAR(50) NOT NULL,
        amount_minor BIGINT NOT NULL,
        currency CHAR(3) NOT NULL REFERENCES currencies(iso_code),
        reason TEXT NOT NULL,
        reference_type VARCHAR(50) NULL,
        reference_id UUID NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by VARCHAR(255) NOT NULL REFERENCES users(user_id)
    );
    """)
    
    # Create vendor_disputes table
    op.execute("""
    CREATE TABLE vendor_disputes (
        dispute_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        settlement_item_id UUID NOT NULL REFERENCES vendor_settlement_items(id) ON DELETE CASCADE,
        vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
        dispute_type VARCHAR(50) NOT NULL,
        dispute_reason TEXT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        resolution VARCHAR(20) NULL,
        resolution_notes TEXT NULL,
        sla_deadline TIMESTAMPTZ NOT NULL,
        resolved_by VARCHAR(255) NULL REFERENCES users(user_id),
        resolved_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NULL
    );
    """)
    
    # Create ledger_accounts table
    op.execute("""
    CREATE TABLE ledger_accounts (
        account_number TEXT PRIMARY KEY,
        account_name TEXT NOT NULL,
        account_type TEXT NOT NULL,
        sub_account_type TEXT NULL,
        tenant_id VARCHAR(255) NULL REFERENCES tenants(tenant_id) ON DELETE SET NULL,
        vendor_id UUID NULL REFERENCES vendors(vendor_id) ON DELETE SET NULL,
        store_id VARCHAR(255) NULL REFERENCES stores(store_id) ON DELETE SET NULL,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK ((tenant_id IS NOT NULL) OR (vendor_id IS NOT NULL) OR (store_id IS NOT NULL))
    );
    """)
    
    # Create approval_chain_steps table
    op.execute("""
    CREATE TABLE approval_chain_steps (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        approval_chain_id UUID NOT NULL REFERENCES approval_chains(chain_id) ON DELETE CASCADE,
        step_number INTEGER NOT NULL,
        approver_role TEXT NOT NULL,
        approver_scope scope_type NOT NULL,
        escalation_after_hours INTEGER NULL,
        is_required BOOLEAN NOT NULL DEFAULT TRUE,
        UNIQUE(approval_chain_id, step_number)
    );
    """)
    
    # Create approval_request_approvers table
    op.execute("""
    CREATE TABLE approval_request_approvers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        approval_request_id INTEGER NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
        user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        step_number INTEGER NOT NULL,
        approved BOOLEAN NULL,
        approved_at TIMESTAMPTZ NULL,
        notes TEXT NULL,
        UNIQUE(approval_request_id, user_id, step_number)
    );
    """)
    
    # Create data_retention_policies table (if not exists)
    op.execute("""
    CREATE TABLE IF NOT EXISTS data_retention_policies (
        policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        table_name VARCHAR(100) NOT NULL,
        retention_period INTERVAL NOT NULL,
        archive_strategy VARCHAR(20) NOT NULL DEFAULT 'delete',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        last_run_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """)


def downgrade() -> None:
    # Drop tables in reverse order
    op.execute("DROP TABLE IF EXISTS data_retention_policies;")
    op.execute("DROP TABLE IF EXISTS approval_request_approvers;")
    op.execute("DROP TABLE IF EXISTS approval_chain_steps;")
    op.execute("DROP TABLE IF EXISTS ledger_accounts;")
    op.execute("DROP TABLE IF EXISTS vendor_disputes;")
    op.execute("DROP TABLE IF EXISTS vendor_settlement_adjustments;")
    op.execute("DROP TABLE IF EXISTS vendor_settlement_items;")
    op.execute("DROP TABLE IF EXISTS vendor_settlement_batches;")
    op.execute("DROP TABLE IF EXISTS refunds;")
    op.execute("DROP TABLE IF EXISTS returns;")
    op.execute("DROP TABLE IF EXISTS pricing_versions;")
    op.execute("DROP TABLE IF EXISTS product_tax_categories;")


