"""billing_v4_tables

Revision ID: 0032_billing_v4_tables
Revises: 0031_add_v2_approval_tables_and_rls_policies
Create Date: 2025-10-07 14:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0032_billing_v4_tables'
down_revision = '0031_add_v2_approval_tables_and_rls_policies'
branch_labels = None
depends_on = None


def upgrade():
    """Add new billing tables for v4.1 architecture"""
    
    # Create vendor_settlements table
    op.create_table('vendor_settlements',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('settlement_number', sa.String(50), nullable=False),
        sa.Column('subtotal_minor', sa.BigInteger(), nullable=False),
        sa.Column('commission_minor', sa.BigInteger(), nullable=False, default=0),
        sa.Column('payout_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('payout_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('export_batch_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('settlement_number'),
        sa.ForeignKeyConstraint(['currency'], ['currencies.iso_code'], name='vendor_settlements_currency_fkey'),
        sa.ForeignKeyConstraint(['export_batch_id'], ['vendor_settlement_batches.id'], name='vendor_settlements_batch_fkey')
    )
    
    # Create vendor_settlement_batches table
    op.create_table('vendor_settlement_batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('batch_number', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='queued'),
        sa.Column('total_payout_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_number'),
        sa.ForeignKeyConstraint(['currency'], ['currencies.iso_code'], name='vendor_settlement_batches_currency_fkey')
    )
    
    # Create vendor_settlement_items table
    op.create_table('vendor_settlement_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('settlement_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('sub_order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('subtotal_minor', sa.BigInteger(), nullable=False),
        sa.Column('commission_minor', sa.BigInteger(), nullable=False, default=0),
        sa.Column('payout_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['settlement_id'], ['vendor_settlements.id'], name='vendor_settlement_items_settlement_fkey'),
        sa.ForeignKeyConstraint(['order_id'], ['orders_new.order_id'], name='vendor_settlement_items_order_fkey'),
        sa.ForeignKeyConstraint(['currency'], ['currencies.iso_code'], name='vendor_settlement_items_currency_fkey')
    )
    
    # Create vendor_settlement_adjustments table
    op.create_table('vendor_settlement_adjustments',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('settlement_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(255), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['settlement_id'], ['vendor_settlements.id'], name='vendor_settlement_adjustments_settlement_fkey'),
        sa.ForeignKeyConstraint(['currency'], ['currencies.iso_code'], name='vendor_settlement_adjustments_currency_fkey'),
        sa.CheckConstraint("type IN ('commission', 'chargeback', 'refund', 'bonus', 'penalty')", name='vendor_settlement_adjustments_type_check'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'denied', 'applied')", name='vendor_settlement_adjustments_status_check')
    )
    
    # Create vendor_disputes table
    op.create_table('vendor_disputes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('settlement_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='open'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['settlement_id'], ['vendor_settlements.id'], name='vendor_disputes_settlement_fkey'),
        sa.ForeignKeyConstraint(['item_id'], ['vendor_settlement_items.id'], name='vendor_disputes_item_fkey'),
        sa.CheckConstraint("status IN ('open', 'investigating', 'resolved', 'closed')", name='vendor_disputes_status_check')
    )
    
    # Enhance trade_invoices table
    op.add_column('trade_invoices', sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('trade_invoices', sa.Column('invoice_number', sa.String(50), nullable=True))
    op.add_column('trade_invoices', sa.Column('status', sa.String(20), nullable=True, default='draft'))
    op.add_column('trade_invoices', sa.Column('tax_total_minor', sa.BigInteger(), nullable=True, default=0))
    op.add_column('trade_invoices', sa.Column('subtotal_minor', sa.BigInteger(), nullable=True))
    
    # Create trade_invoice_lines table
    op.create_table('trade_invoice_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price_minor', sa.BigInteger(), nullable=False),
        sa.Column('line_total_minor', sa.BigInteger(), nullable=False),
        sa.Column('tax_minor', sa.BigInteger(), nullable=False, default=0),
        sa.Column('tax_code', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['invoice_id'], ['trade_invoices.id'], name='trade_invoice_lines_invoice_fkey')
    )
    
    # Create outbox_events table if it doesn't exist
    op.create_table('billing_outbox_events',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('aggregate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_data', sa.Text(), nullable=False),
        sa.Column('event_version', sa.Integer(), nullable=False, default=1),
        sa.Column('event_timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=False, default=3),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('event_id')
    )
    
    # Create indexes for performance
    op.create_index('idx_vendor_settlements_vendor_id', 'vendor_settlements', ['vendor_id'])
    op.create_index('idx_vendor_settlements_tenant_id', 'vendor_settlements', ['tenant_id'])
    op.create_index('idx_vendor_settlements_status', 'vendor_settlements', ['status'])
    op.create_index('idx_vendor_settlement_items_settlement_id', 'vendor_settlement_items', ['settlement_id'])
    op.create_index('idx_vendor_settlement_items_order_id', 'vendor_settlement_items', ['order_id'])
    op.create_index('idx_vendor_disputes_tenant_id', 'vendor_disputes', ['tenant_id'])
    op.create_index('idx_vendor_disputes_status', 'vendor_disputes', ['status'])
    op.create_index('idx_trade_invoices_tenant_id', 'trade_invoices', ['tenant_id'])
    op.create_index('idx_trade_invoices_status', 'trade_invoices', ['status'])
    op.create_index('idx_billing_outbox_events_status', 'billing_outbox_events', ['status'])
    
    # Enable RLS on new tables
    op.execute('ALTER TABLE vendor_settlements ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE vendor_settlement_batches ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE vendor_settlement_items ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE vendor_settlement_adjustments ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE vendor_disputes ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE trade_invoices ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE trade_invoice_lines ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE billing_outbox_events ENABLE ROW LEVEL SECURITY')
    
    # Create RLS policies for tenant isolation
    op.execute("""
        CREATE POLICY vendor_settlements_tenant_isolation ON vendor_settlements
            FOR ALL TO PUBLIC
            USING (tenant_id = current_setting('app.current_tenant_id')::UUID)
    """)
    
    op.execute("""
        CREATE POLICY vendor_settlement_items_tenant_isolation ON vendor_settlement_items
            FOR ALL TO PUBLIC
            USING (EXISTS (
                SELECT 1 FROM vendor_settlements vs 
                WHERE vs.id = vendor_settlement_items.settlement_id 
                AND vs.tenant_id = current_setting('app.current_tenant_id')::UUID
            ))
    """)
    
    op.execute("""
        CREATE POLICY vendor_settlement_adjustments_tenant_isolation ON vendor_settlement_adjustments
            FOR ALL TO PUBLIC
            USING (EXISTS (
                SELECT 1 FROM vendor_settlements vs 
                WHERE vs.id = vendor_settlement_adjustments.settlement_id 
                AND vs.tenant_id = current_setting('app.current_tenant_id')::UUID
            ))
    """)
    
    op.execute("""
        CREATE POLICY vendor_disputes_tenant_isolation ON vendor_disputes
            FOR ALL TO PUBLIC
            USING (tenant_id = current_setting('app.current_tenant_id')::UUID)
    """)
    
    op.execute("""
        CREATE POLICY trade_invoices_tenant_isolation ON trade_invoices
            FOR ALL TO PUBLIC
            USING (tenant_id = current_setting('app.current_tenant_id')::UUID)
    """)
    
    op.execute("""
        CREATE POLICY trade_invoice_lines_tenant_isolation ON trade_invoice_lines
            FOR ALL TO PUBLIC
            USING (EXISTS (
                SELECT 1 FROM trade_invoices ti 
                WHERE ti.id = trade_invoice_lines.invoice_id 
                AND ti.tenant_id = current_setting('app.current_tenant_id')::UUID
            ))
    """)


def downgrade():
    """Remove new billing tables"""
    
    # Drop RLS policies
    op.execute('DROP POLICY IF EXISTS vendor_settlements_tenant_isolation ON vendor_settlements')
    op.execute('DROP POLICY IF EXISTS vendor_settlement_items_tenant_isolation ON vendor_settlement_items')
    op.execute('DROP POLICY IF EXISTS vendor_settlement_adjustments_tenant_isolation ON vendor_settlement_adjustments')
    op.execute('DROP POLICY IF EXISTS vendor_disputes_tenant_isolation ON vendor_disputes')
    op.execute('DROP POLICY IF EXISTS trade_invoices_tenant_isolation ON trade_invoices')
    op.execute('DROP POLICY IF EXISTS trade_invoice_lines_tenant_isolation ON trade_invoice_lines')
    
    # Drop indexes
    op.drop_index('idx_billing_outbox_events_status', table_name='billing_outbox_events')
    op.drop_index('idx_trade_invoices_status', table_name='trade_invoices')
    op.drop_index('idx_trade_invoices_tenant_id', table_name='trade_invoices')
    op.drop_index('idx_vendor_disputes_status', table_name='vendor_disputes')
    op.drop_index('idx_vendor_disputes_tenant_id', table_name='vendor_disputes')
    op.drop_index('idx_vendor_settlement_items_order_id', table_name='vendor_settlement_items')
    op.drop_index('idx_vendor_settlement_items_settlement_id', table_name='vendor_settlement_items')
    op.drop_index('idx_vendor_settlements_status', table_name='vendor_settlements')
    op.drop_index('idx_vendor_settlements_tenant_id', table_name='vendor_settlements')
    op.drop_index('idx_vendor_settlements_vendor_id', table_name='vendor_settlements')
    
    # Drop tables
    op.drop_table('billing_outbox_events')
    op.drop_table('trade_invoice_lines')
    op.drop_table('vendor_disputes')
    op.drop_table('vendor_settlement_adjustments')
    op.drop_table('vendor_settlement_items')
    op.drop_table('vendor_settlement_batches')
    op.drop_table('vendor_settlements')
    
    # Remove columns from trade_invoices
    op.drop_column('trade_invoices', 'subtotal_minor')
    op.drop_column('trade_invoices', 'tax_total_minor')
    op.drop_column('trade_invoices', 'status')
    op.drop_column('trade_invoices', 'invoice_number')
    op.drop_column('trade_invoices', 'tenant_id')
