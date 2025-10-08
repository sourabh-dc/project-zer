"""ledger_v4_1_tables

Revision ID: 0038
Revises: 0037_cv_v4_1_tables
Create Date: 2025-10-07 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '0038_ledger_v4_1_tables'
down_revision = '0037_cv_v4_1_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Create ledger_entries_new table
    op.create_table('ledger_entries_new',
        sa.Column('id', sa.UUID(as_uuid=True), nullable=False, default=uuid.uuid4),
        sa.Column('tenant_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', sa.UUID(as_uuid=True), nullable=True),
        sa.Column('account', sa.String(100), nullable=False),
        sa.Column('entry_type', sa.String(20), nullable=False),  # debit/credit
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('cost_centre_id', sa.UUID(as_uuid=True), nullable=True),
        sa.Column('site_id', sa.UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', sa.UUID(as_uuid=True), nullable=True),
        sa.Column('reference_type', sa.String(50), nullable=True),  # order, invoice, approval
        sa.Column('reference_id', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create account_balances_new table for precomputed balances
    op.create_table('account_balances_new',
        sa.Column('id', sa.UUID(as_uuid=True), nullable=False, default=uuid.uuid4),
        sa.Column('tenant_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('account', sa.String(100), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('balance_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'account', 'currency', name='uq_account_balances_new')
    )
    
    # Create indexes for performance
    op.create_index(op.f('ix_ledger_entries_new_tenant_id'), 'ledger_entries_new', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_account'), 'ledger_entries_new', ['account'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_currency'), 'ledger_entries_new', ['currency'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_reference'), 'ledger_entries_new', ['reference_type', 'reference_id'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_created_at'), 'ledger_entries_new', ['created_at'], unique=False)
    
    op.create_index(op.f('ix_account_balances_new_tenant_id'), 'account_balances_new', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_account_balances_new_account'), 'account_balances_new', ['account'], unique=False)
    op.create_index(op.f('ix_account_balances_new_currency'), 'account_balances_new', ['currency'], unique=False)
    
    # Add RLS policies
    op.execute("""
        ALTER TABLE ledger_entries_new ENABLE ROW LEVEL SECURITY;
        CREATE POLICY ledger_entries_new_tenant_isolation ON ledger_entries_new
        USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)
    
    op.execute("""
        ALTER TABLE account_balances_new ENABLE ROW LEVEL SECURITY;
        CREATE POLICY account_balances_new_tenant_isolation ON account_balances_new
        USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)
    
    # Migrate data from legacy ledger_entries table if it exists
    op.execute("""
        INSERT INTO ledger_entries_new (
            id, tenant_id, account, entry_type, amount_minor, currency,
            cost_centre_id, site_id, store_id, reference_type, reference_id,
            description, created_at
        )
        SELECT 
            gen_random_uuid()::uuid,  -- Generate new UUIDs
            COALESCE(tenant_id, '550e8400-e29b-41d4-a716-446655440000')::uuid,  -- Default tenant if null
            account, entry_type, amount_minor, currency,
            cost_centre_id, site_id, store_id, reference_type, reference_id,
            description, COALESCE(occurred_at, now())
        FROM ledger_entries
        WHERE EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ledger_entries')
    """)
    
    # Compute initial balances from migrated data
    op.execute("""
        INSERT INTO account_balances_new (tenant_id, account, currency, balance_minor, last_updated, created_at)
        SELECT 
            tenant_id, account, currency,
            SUM(CASE WHEN entry_type='debit' THEN amount_minor ELSE -amount_minor END) as balance_minor,
            MAX(created_at) as last_updated,
            MIN(created_at) as created_at
        FROM ledger_entries_new
        GROUP BY tenant_id, account, currency
        ON CONFLICT (tenant_id, account, currency) DO NOTHING
    """)


def downgrade():
    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS ledger_entries_new_tenant_isolation ON ledger_entries_new;")
    op.execute("DROP POLICY IF EXISTS account_balances_new_tenant_isolation ON account_balances_new;")
    
    # Drop indexes
    op.drop_index(op.f('ix_account_balances_new_currency'), table_name='account_balances_new')
    op.drop_index(op.f('ix_account_balances_new_account'), table_name='account_balances_new')
    op.drop_index(op.f('ix_account_balances_new_tenant_id'), table_name='account_balances_new')
    
    op.drop_index(op.f('ix_ledger_entries_new_created_at'), table_name='ledger_entries_new')
    op.drop_index(op.f('ix_ledger_entries_new_reference'), table_name='ledger_entries_new')
    op.drop_index(op.f('ix_ledger_entries_new_currency'), table_name='ledger_entries_new')
    op.drop_index(op.f('ix_ledger_entries_new_account'), table_name='ledger_entries_new')
    op.drop_index(op.f('ix_ledger_entries_new_tenant_id'), table_name='ledger_entries_new')
    
    # Drop tables
    op.drop_table('account_balances_new')
    op.drop_table('ledger_entries_new')
