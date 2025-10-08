"""payments_v4_1_tables

Revision ID: 0039
Revises: 0038_ledger_v4_1_tables
Create Date: 2025-10-07 21:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '0039_payments_v4_1_tables'
down_revision = '0038_ledger_v4_1_tables'
branch_labels = None
depends_on = None


def upgrade():
    """Create V4.1 payment tables with multi-provider support"""
    
    # Create payment_transactions_new table
    op.create_table(
        'payment_transactions_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vendors.vendor_id'), nullable=True),
        sa.Column('provider', sa.String(50), nullable=False, comment='stripe, adyen, paypal, etc.'),
        sa.Column('payment_intent_id', sa.String(255), nullable=True),
        sa.Column('charge_id', sa.String(255), nullable=True),
        sa.Column('amount_minor', sa.BigInteger, nullable=False, comment='Amount in minor units'),
        sa.Column('currency', sa.String(3), sa.ForeignKey('currencies.code'), nullable=False, default='GBP'),
        sa.Column('status', sa.String(50), nullable=False, comment='pending, succeeded, failed, refunded'),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('raw_response', postgresql.JSONB, nullable=True, comment='Raw provider response'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        
        # Indexes
        sa.Index('idx_payment_transactions_tenant_id', 'tenant_id'),
        sa.Index('idx_payment_transactions_provider', 'provider'),
        sa.Index('idx_payment_transactions_status', 'status'),
        sa.Index('idx_payment_transactions_payment_intent_id', 'payment_intent_id'),
        sa.Index('idx_payment_transactions_charge_id', 'charge_id'),
        sa.Index('idx_payment_transactions_order_id', 'order_id'),
    )
    
    # Create customers_new table
    op.create_table(
        'customers_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False, comment='stripe, adyen, paypal, etc.'),
        sa.Column('external_customer_id', sa.String(255), nullable=False, comment='Provider customer ID'),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        
        # Unique constraint for tenant + provider + external_customer_id
        sa.UniqueConstraint('tenant_id', 'provider', 'external_customer_id', name='uq_customers_new'),
        
        # Indexes
        sa.Index('idx_customers_tenant_id', 'tenant_id'),
        sa.Index('idx_customers_provider', 'provider'),
        sa.Index('idx_customers_external_id', 'external_customer_id'),
        sa.Index('idx_customers_email', 'email'),
    )
    
    # Create payment_refunds table
    op.create_table(
        'payment_refunds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('payment_transaction_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payment_transactions_new.id'), nullable=False),
        sa.Column('refund_id', sa.String(255), nullable=True, comment='Provider refund ID'),
        sa.Column('amount_minor', sa.BigInteger, nullable=False, comment='Refund amount in minor units'),
        sa.Column('currency', sa.String(3), nullable=False, default='GBP'),
        sa.Column('reason', sa.String(255), nullable=True, comment='Refund reason'),
        sa.Column('status', sa.String(50), nullable=False, comment='pending, succeeded, failed'),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        
        # Indexes
        sa.Index('idx_payment_refunds_tenant_id', 'tenant_id'),
        sa.Index('idx_payment_refunds_transaction_id', 'payment_transaction_id'),
        sa.Index('idx_payment_refunds_refund_id', 'refund_id'),
        sa.Index('idx_payment_refunds_status', 'status'),
    )
    
    # Create payment_adjustments table
    op.create_table(
        'payment_adjustments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('payment_transaction_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('payment_transactions_new.id'), nullable=False),
        sa.Column('adjustment_type', sa.String(50), nullable=False, comment='discount, fee, tax, etc.'),
        sa.Column('amount_minor', sa.BigInteger, nullable=False, comment='Adjustment amount in minor units'),
        sa.Column('currency', sa.String(3), nullable=False, default='GBP'),
        sa.Column('reason', sa.String(255), nullable=True, comment='Adjustment reason'),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        
        # Indexes
        sa.Index('idx_payment_adjustments_tenant_id', 'tenant_id'),
        sa.Index('idx_payment_adjustments_transaction_id', 'payment_transaction_id'),
        sa.Index('idx_payment_adjustments_type', 'adjustment_type'),
    )
    
    # Add payment provider configuration to zeroque_rails if not exists
    op.execute("""
        INSERT INTO zeroque_rails (tenant_id, type, name, config, active, created_at, updated_at)
        SELECT 
            tenant_id,
            'payment' as type,
            'stripe' as name,
            '{"api_key": "sk_test_default", "webhook_secret": "whsec_default", "base_url": "https://api.stripe.com/v1"}'::jsonb as config,
            true as active,
            NOW() as created_at,
            NOW() as updated_at
        FROM tenants
        WHERE NOT EXISTS (
            SELECT 1 FROM zeroque_rails 
            WHERE type = 'payment' AND name = 'stripe' AND tenant_id = tenants.tenant_id
        )
    """)
    
    # Create RLS policies for payment tables
    op.execute("""
        -- Enable RLS on payment tables
        ALTER TABLE payment_transactions_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE customers_new ENABLE ROW LEVEL SECURITY;
        ALTER TABLE payment_refunds ENABLE ROW LEVEL SECURITY;
        ALTER TABLE payment_adjustments ENABLE ROW LEVEL SECURITY;
        
        -- Create RLS policies for payment_transactions_new
        CREATE POLICY payment_transactions_tenant_isolation ON payment_transactions_new
            FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        
        -- Create RLS policies for customers_new
        CREATE POLICY customers_tenant_isolation ON customers_new
            FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        
        -- Create RLS policies for payment_refunds
        CREATE POLICY payment_refunds_tenant_isolation ON payment_refunds
            FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        
        -- Create RLS policies for payment_adjustments
        CREATE POLICY payment_adjustments_tenant_isolation ON payment_adjustments
            FOR ALL USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
    """)


def downgrade():
    """Drop V4.1 payment tables"""
    
    # Drop RLS policies
    op.execute("""
        DROP POLICY IF EXISTS payment_transactions_tenant_isolation ON payment_transactions_new;
        DROP POLICY IF EXISTS customers_tenant_isolation ON customers_new;
        DROP POLICY IF EXISTS payment_refunds_tenant_isolation ON payment_refunds;
        DROP POLICY IF EXISTS payment_adjustments_tenant_isolation ON payment_adjustments;
    """)
    
    # Drop tables in reverse order
    op.drop_table('payment_adjustments')
    op.drop_table('payment_refunds')
    op.drop_table('customers_new')
    op.drop_table('payment_transactions_new')
    
    # Remove payment provider configurations from zeroque_rails
    op.execute("DELETE FROM zeroque_rails WHERE type = 'payment'")
