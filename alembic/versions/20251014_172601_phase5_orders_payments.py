"""Phase 5: Orders & Payments

Revision ID: phase5_orders_payments
Revises: phase4_budgets_spend
Create Date: 2025-01-14 07:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'phase5_orders_payments'
down_revision = 'phase4_budgets_spend'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('trade_accounts',
        sa.Column('trade_account_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('account_number', sa.String(100), nullable=False),
        sa.Column('company_name', sa.String(200), nullable=False),
        sa.Column('contact_email', sa.String(255), nullable=False),
        sa.Column('credit_limit_minor', sa.BigInteger(), nullable=False),
        sa.Column('available_credit_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('payment_terms_days', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ),
        sa.PrimaryKeyConstraint('trade_account_id'),
        sa.UniqueConstraint('account_number')
        )

    # Create payment_intents table
    op.create_table('payment_intents',
        sa.Column('payment_intent_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=True),
        sa.Column('trade_account_id', sa.UUID(), nullable=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('provider_intent_id', sa.String(255), nullable=True),
        sa.Column('payment_method', sa.String(50), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('succeeded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ),
        sa.ForeignKeyConstraint(['trade_account_id'], ['trade_accounts.trade_account_id'], ),
        sa.PrimaryKeyConstraint('payment_intent_id')
        )


    # Create currency_rates table
    op.create_table('currency_rates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('base_currency', sa.String(3), nullable=False),
        sa.Column('target_currency', sa.String(3), nullable=False),
        sa.Column('rate', sa.Numeric(15, 8), nullable=False),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('base_currency', 'target_currency', 'valid_from', name='uq_currency_rate')
    )

    # Create payment_webhooks table

    op.create_table('payment_webhooks',
        sa.Column('webhook_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', sa.JSON(), nullable=False),
        sa.Column('processed', sa.Boolean(), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ),
        sa.PrimaryKeyConstraint('webhook_id')
    )
    # Create indexes for performance
    op.create_index(op.f('ix_trade_accounts_tenant_id'), 'trade_accounts', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_trade_accounts_account_number'), 'trade_accounts', ['account_number'], unique=True)
    op.create_index(op.f('ix_payment_intents_tenant_id'), 'payment_intents', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_payment_intents_trade_account_id'), 'payment_intents', ['trade_account_id'], unique=False)
    op.create_index(op.f('ix_payment_webhooks_tenant_id'), 'payment_webhooks', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_payment_webhooks_provider'), 'payment_webhooks', ['provider'], unique=False)

    # Phase 6: Dashboard tables for Power BI integration
    # Create dashboards table
    op.create_table('dashboards',
        sa.Column('dashboard_id', sa.String(), nullable=False),
        sa.Column('tenant_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('dashboard_type', sa.String(50), nullable=False),
        sa.Column('powerbi_workspace_id', sa.String(100), nullable=True),
        sa.Column('powerbi_report_id', sa.String(100), nullable=True),
        sa.Column('powerbi_dataset_id', sa.String(100), nullable=True),
        sa.Column('embed_config', sa.JSON(), nullable=False),
        sa.Column('data_sources', sa.JSON(), nullable=False),
        sa.Column('refresh_schedule', sa.String(100), nullable=True),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('is_public', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('dashboard_id')
    )

    # Create dashboard_access table
    op.create_table('dashboard_access',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dashboard_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('role_id', sa.String(), nullable=True),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create dashboard_data_refresh table
    op.create_table('dashboard_data_refresh',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('dashboard_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('last_refresh', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_refresh', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('refresh_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('records_processed', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for Phase 6 tables
    op.create_index(op.f('ix_dashboards_tenant_id'), 'dashboards', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_dashboards_dashboard_type'), 'dashboards', ['dashboard_type'], unique=False)
    op.create_index(op.f('ix_dashboard_access_dashboard_id'), 'dashboard_access', ['dashboard_id'], unique=False)
    op.create_index(op.f('ix_dashboard_data_refresh_dashboard_id'), 'dashboard_data_refresh', ['dashboard_id'], unique=False)

    # Phase 7: Enhance existing audit_logs table for compliance
    # Add new columns to audit_logs table
    op.add_column('audit_logs', sa.Column('session_id', sa.String(100), nullable=True))
    op.add_column('audit_logs', sa.Column('correlation_id', sa.String(100), nullable=True))
    op.add_column('audit_logs', sa.Column('severity', sa.String(20), nullable=False, server_default='info'))
    op.add_column('audit_logs', sa.Column('category', sa.String(50), nullable=False, server_default='system'))
    op.add_column('audit_logs', sa.Column('retention_until', sa.DateTime(timezone=True), nullable=True))

    # Create indexes for Phase 7 audit log enhancements
    op.create_index(op.f('ix_audit_logs_severity'), 'audit_logs', ['severity'], unique=False)
    op.create_index(op.f('ix_audit_logs_category'), 'audit_logs', ['category'], unique=False)
    op.create_index(op.f('ix_audit_logs_correlation_id'), 'audit_logs', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_session_id'), 'audit_logs', ['session_id'], unique=False)


def downgrade():
    # Remove Phase 7 audit log indexes
    try:
        op.drop_index(op.f('ix_audit_logs_session_id'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_correlation_id'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_category'), table_name='audit_logs')
        op.drop_index(op.f('ix_audit_logs_severity'), table_name='audit_logs')
    except:
        pass

    # Remove Phase 7 audit log columns
    try:
        op.drop_column('audit_logs', 'retention_until')
        op.drop_column('audit_logs', 'category')
        op.drop_column('audit_logs', 'severity')
        op.drop_column('audit_logs', 'correlation_id')
        op.drop_column('audit_logs', 'session_id')
    except:
        pass

    # Remove Phase 6 indexes
    try:
        op.drop_index(op.f('ix_dashboard_data_refresh_dashboard_id'), table_name='dashboard_data_refresh')
        op.drop_index(op.f('ix_dashboard_access_dashboard_id'), table_name='dashboard_access')
        op.drop_index(op.f('ix_dashboards_dashboard_type'), table_name='dashboards')
        op.drop_index(op.f('ix_dashboards_tenant_id'), table_name='dashboards')
    except:
        pass

    # Drop Phase 6 tables
    try:
        op.drop_table('dashboard_data_refresh')
        op.drop_table('dashboard_access')
        op.drop_table('dashboards')
    except:
        pass

    # Remove Phase 5 indexes
    try:
        op.drop_index(op.f('ix_payment_webhooks_provider'), table_name='payment_webhooks')
        op.drop_index(op.f('ix_payment_webhooks_tenant_id'), table_name='payment_webhooks')
        op.drop_index(op.f('ix_payment_intents_trade_account_id'), table_name='payment_intents')
        op.drop_index(op.f('ix_payment_intents_tenant_id'), table_name='payment_intents')
        op.drop_index(op.f('ix_trade_accounts_account_number'), table_name='trade_accounts')
        op.drop_index(op.f('ix_trade_accounts_tenant_id'), table_name='trade_accounts')
    except:
        pass

    # Drop Phase 5 tables
    try:
        op.drop_table('payment_webhooks')
        op.drop_table('currency_rates')
        op.drop_table('payment_intents')
        op.drop_table('trade_accounts')
    except:
        pass
