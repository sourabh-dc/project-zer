"""add_idempotency_table

Revision ID: 8ae44f20fdc6
Revises: phase5_orders_payments
Create Date: 2025-10-27 13:52:50.969857+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8ae44f20fdc6'
down_revision = 'phase5_orders_payments'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Create idempotency and ledger tables"""
    from sqlalchemy.dialects.postgresql import UUID

    # Create idempotency_records table
    op.create_table('idempotency_records',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('idempotency_key', sa.String(255), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('request_hash', sa.String(255), nullable=False),
        sa.Column('response_data', sa.JSON(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_idempotency_records_idempotency_key'), 'idempotency_records', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_idempotency_records_tenant_id'), 'idempotency_records', ['tenant_id'], unique=False)

    # Create ledger_entries_new table (if not exists)

    op.create_table('ledger_entries_new',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('vendor_id', UUID(as_uuid=True), nullable=True),
        sa.Column('account', sa.String(100), nullable=False),
        sa.Column('entry_type', sa.String(20), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('cost_centre_id', UUID(as_uuid=True), nullable=True),
        sa.Column('site_id', UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', UUID(as_uuid=True), nullable=True),
        sa.Column('reference_type', sa.String(50), nullable=True),
        sa.Column('reference_id', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('entry_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ledger_entries_new_tenant_id'), 'ledger_entries_new', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_account'), 'ledger_entries_new', ['account'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_currency'), 'ledger_entries_new', ['currency'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_reference_type'), 'ledger_entries_new', ['reference_type'], unique=False)
    op.create_index(op.f('ix_ledger_entries_new_reference_id'), 'ledger_entries_new', ['reference_id'], unique=False)


    # Create account_balances_new table (if not exists)
    op.create_table('account_balances_new',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account', sa.String(100), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('balance_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_account_balances_new_tenant_id'), 'account_balances_new', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_account_balances_new_account_currency'), 'account_balances_new', ['account', 'currency'], unique=True)

    # Create outbox_events table (if not exists)
    op.create_table('outbox_events',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbox_events_status'), 'outbox_events', ['status'], unique=False)
    op.create_index(op.f('ix_outbox_events_tenant_id'), 'outbox_events', ['tenant_id'], unique=False)


    # Create audit_logs table (if not exists)
    op.create_table('audit_logs',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('session_id', sa.String(100), nullable=True),
        sa.Column('correlation_id', sa.String(100), nullable=True),
        sa.Column('severity', sa.String(20), nullable=False, server_default='info'),
        sa.Column('category', sa.String(50), nullable=False, server_default='system'),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_tenant_id'), 'audit_logs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource_type'), 'audit_logs', ['resource_type'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    """Drop idempotency and ledger tables"""
    # Drop idempotency_records table
    try:
        op.drop_index(op.f('ix_idempotency_records_tenant_id'), table_name='idempotency_records')
        op.drop_index(op.f('ix_idempotency_records_idempotency_key'), table_name='idempotency_records')
        op.drop_table('idempotency_records')
    except:
        pass

    # Drop ledger tables (if they were created by this migration)
    try:
        op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_resource_type'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_tenant_id'), table_name='audit_logs')
        op.drop_table('audit_logs')
    except:
        pass

    try:
        op.drop_index(op.f('ix_outbox_events_tenant_id'), table_name='outbox_events')
        op.drop_index(op.f('ix_outbox_events_status'), table_name='outbox_events')
        op.drop_table('outbox_events')
    except:
        pass

    try:
        op.drop_index(op.f('ix_account_balances_new_account_currency'), table_name='account_balances_new')
        op.drop_index(op.f('ix_account_balances_new_tenant_id'), table_name='account_balances_new')
        op.drop_table('account_balances_new')
    except:
        pass

    try:
        op.drop_index(op.f('ix_ledger_entries_new_reference_id'), table_name='ledger_entries_new')
        op.drop_index(op.f('ix_ledger_entries_new_reference_type'), table_name='ledger_entries_new')
        op.drop_index(op.f('ix_ledger_entries_new_currency'), table_name='ledger_entries_new')
        op.drop_index(op.f('ix_ledger_entries_new_account'), table_name='ledger_entries_new')
        op.drop_index(op.f('ix_ledger_entries_new_tenant_id'), table_name='ledger_entries_new')
        op.drop_table('ledger_entries_new')
    except:
        pass


