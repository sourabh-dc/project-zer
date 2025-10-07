"""fix_billing_schema_v4_1

Revision ID: 0033_fix_billing_schema_v4_1
Revises: 0032_billing_v4_tables
Create Date: 2025-10-07 11:21:26.782186+00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '0033_fix_billing_schema_v4_1'
down_revision = '0032_billing_v4_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Fix Billing Service Schema for V4.1 Architecture - Add missing tenant_id columns and RLS policies"""
    
    # Add tenant_id to vendor_settlements
    op.add_column('vendor_settlements', sa.Column('tenant_id', sa.UUID(), nullable=True))
    
    # Add tenant_id to vendor_settlement_items
    op.add_column('vendor_settlement_items', sa.Column('tenant_id', sa.UUID(), nullable=True))
    
    # Add tenant_id to vendor_disputes
    op.add_column('vendor_disputes', sa.Column('tenant_id', sa.UUID(), nullable=True))
    
    # Add tenant_id to vendor_settlement_adjustments
    op.add_column('vendor_settlement_adjustments', sa.Column('tenant_id', sa.UUID(), nullable=True))
    
    # Add tenant_id to vendor_settlement_batches
    op.add_column('vendor_settlement_batches', sa.Column('tenant_id', sa.UUID(), nullable=True))
    
    # Update existing records with a default tenant_id (temporary fix)
    op.execute(text("UPDATE vendor_settlements SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL"))
    op.execute(text("UPDATE vendor_settlement_items SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL"))
    op.execute(text("UPDATE vendor_disputes SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL"))
    op.execute(text("UPDATE vendor_settlement_adjustments SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL"))
    op.execute(text("UPDATE vendor_settlement_batches SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL"))
    
    # Make tenant_id NOT NULL after setting defaults
    op.alter_column('vendor_settlements', 'tenant_id', nullable=False)
    op.alter_column('vendor_settlement_items', 'tenant_id', nullable=False)
    op.alter_column('vendor_disputes', 'tenant_id', nullable=False)
    op.alter_column('vendor_settlement_adjustments', 'tenant_id', nullable=False)
    op.alter_column('vendor_settlement_batches', 'tenant_id', nullable=False)
    
    # Create indexes for performance
    op.create_index('idx_vendor_settlements_tenant_id', 'vendor_settlements', ['tenant_id'])
    op.create_index('idx_vendor_settlement_items_tenant_id', 'vendor_settlement_items', ['tenant_id'])
    op.create_index('idx_vendor_disputes_tenant_id', 'vendor_disputes', ['tenant_id'])
    op.create_index('idx_vendor_settlement_adjustments_tenant_id', 'vendor_settlement_adjustments', ['tenant_id'])
    op.create_index('idx_vendor_settlement_batches_tenant_id', 'vendor_settlement_batches', ['tenant_id'])
    
    # Enable RLS on tables
    op.execute(text("ALTER TABLE vendor_settlements ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE vendor_settlement_items ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE vendor_disputes ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE vendor_settlement_adjustments ENABLE ROW LEVEL SECURITY"))
    op.execute(text("ALTER TABLE vendor_settlement_batches ENABLE ROW LEVEL SECURITY"))
    
    # Create RLS policies for tenant isolation
    op.execute(text("DROP POLICY IF EXISTS vendor_settlements_tenant_isolation ON vendor_settlements"))
    op.execute(text("CREATE POLICY vendor_settlements_tenant_isolation ON vendor_settlements FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id')::UUID)"))
    
    op.execute(text("DROP POLICY IF EXISTS vendor_settlement_items_tenant_isolation ON vendor_settlement_items"))
    op.execute(text("CREATE POLICY vendor_settlement_items_tenant_isolation ON vendor_settlement_items FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id')::UUID)"))
    
    op.execute(text("DROP POLICY IF EXISTS vendor_disputes_tenant_isolation ON vendor_disputes"))
    op.execute(text("CREATE POLICY vendor_disputes_tenant_isolation ON vendor_disputes FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id')::UUID)"))
    
    op.execute(text("DROP POLICY IF EXISTS vendor_settlement_adjustments_tenant_isolation ON vendor_settlement_adjustments"))
    op.execute(text("CREATE POLICY vendor_settlement_adjustments_tenant_isolation ON vendor_settlement_adjustments FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id')::UUID)"))
    
    op.execute(text("DROP POLICY IF EXISTS vendor_settlement_batches_tenant_isolation ON vendor_settlement_batches"))
    op.execute(text("CREATE POLICY vendor_settlement_batches_tenant_isolation ON vendor_settlement_batches FOR ALL TO PUBLIC USING (tenant_id = current_setting('app.current_tenant_id')::UUID)"))
    
    # Enhance trade_invoices table if needed
    op.execute(text("""
        DO $$
        BEGIN
            -- Add columns to trade_invoices if they don't exist
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'trade_invoices' AND column_name = 'tenant_id') THEN
                ALTER TABLE trade_invoices ADD COLUMN tenant_id UUID;
                UPDATE trade_invoices SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL;
                ALTER TABLE trade_invoices ALTER COLUMN tenant_id SET NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_trade_invoices_tenant_id ON trade_invoices(tenant_id);
                ALTER TABLE trade_invoices ENABLE ROW LEVEL SECURITY;
                EXECUTE 'CREATE POLICY trade_invoices_tenant_isolation ON trade_invoices FOR ALL TO PUBLIC USING (tenant_id = current_setting(''app.current_tenant_id'')::UUID)';
            END IF;
            
            -- Add status column if it doesn't exist
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'trade_invoices' AND column_name = 'status') THEN
                ALTER TABLE trade_invoices ADD COLUMN status VARCHAR(20) DEFAULT 'draft';
                UPDATE trade_invoices SET status = 'posted' WHERE status IS NULL;
            END IF;
            
            -- Add invoice_number column if it doesn't exist
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'trade_invoices' AND column_name = 'invoice_number') THEN
                ALTER TABLE trade_invoices ADD COLUMN invoice_number VARCHAR(50);
                CREATE INDEX IF NOT EXISTS idx_trade_invoices_invoice_number ON trade_invoices(invoice_number);
            END IF;
        END $$;
    """))


def downgrade() -> None:
    """Revert billing schema changes"""
    
    # Drop RLS policies
    op.execute(text("DROP POLICY IF EXISTS vendor_settlements_tenant_isolation ON vendor_settlements"))
    op.execute(text("DROP POLICY IF EXISTS vendor_settlement_items_tenant_isolation ON vendor_settlement_items"))
    op.execute(text("DROP POLICY IF EXISTS vendor_disputes_tenant_isolation ON vendor_disputes"))
    op.execute(text("DROP POLICY IF EXISTS vendor_settlement_adjustments_tenant_isolation ON vendor_settlement_adjustments"))
    op.execute(text("DROP POLICY IF EXISTS vendor_settlement_batches_tenant_isolation ON vendor_settlement_batches"))
    op.execute(text("DROP POLICY IF EXISTS trade_invoices_tenant_isolation ON trade_invoices"))
    
    # Drop indexes
    op.drop_index('idx_vendor_settlements_tenant_id', 'vendor_settlements')
    op.drop_index('idx_vendor_settlement_items_tenant_id', 'vendor_settlement_items')
    op.drop_index('idx_vendor_disputes_tenant_id', 'vendor_disputes')
    op.drop_index('idx_vendor_settlement_adjustments_tenant_id', 'vendor_settlement_adjustments')
    op.drop_index('idx_vendor_settlement_batches_tenant_id', 'vendor_settlement_batches')
    
    # Drop tenant_id columns
    op.drop_column('vendor_settlements', 'tenant_id')
    op.drop_column('vendor_settlement_items', 'tenant_id')
    op.drop_column('vendor_disputes', 'tenant_id')
    op.drop_column('vendor_settlement_adjustments', 'tenant_id')
    op.drop_column('vendor_settlement_batches', 'tenant_id')


