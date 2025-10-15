"""Create all service tables

Revision ID: 0044_comprehensive_v4_1_tables
Revises: 
Create Date: 2024-10-10 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0044_comprehensive_v4_1_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create all service tables"""
    
    # Provisioning Service Tables
    op.create_table('tenants_new',
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('tenant_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('tenant_id'),
        sa.UniqueConstraint('name')
    )
    
    op.create_table('sites_new',
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('site_type', sa.String(length=50), nullable=True),
        sa.Column('geo', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('site_id')
    )
    op.create_index(op.f('ix_sites_new_tenant_id'), 'sites_new', ['tenant_id'], unique=False)
    
    op.create_table('stores_new',
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('store_type', sa.String(length=50), nullable=True),
        sa.Column('geo', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['site_id'], ['sites_new.site_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('store_id')
    )
    op.create_index(op.f('ix_stores_new_site_id'), 'stores_new', ['site_id'], unique=False)
    
    op.create_table('users_new',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('api_key', sa.String(length=255), nullable=True),
        sa.Column('api_key_created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('permissions', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
        sa.UniqueConstraint('api_key'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_new_api_key'), 'users_new', ['api_key'], unique=False)
    op.create_index(op.f('ix_users_new_tenant_id'), 'users_new', ['tenant_id'], unique=False)
    
    op.create_table('roles_new',
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('role_id'),
        sa.UniqueConstraint('code')
    )
    
    op.create_table('vendors_new',
        sa.Column('vendor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('contact_email', sa.String(length=255), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants_new.tenant_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('vendor_id')
    )

    # Outbox and Audit Tables
    op.create_table('outbox_events',
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('aggregate_id', sa.String(length=255), nullable=False),
        sa.Column('event_data', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index(op.f('ix_outbox_events_event_type'), 'outbox_events', ['event_type'], unique=False)
    
    op.create_table('audit_logs',
        sa.Column('log_id', sa.String(length=255), nullable=False),
        sa.Column('aggregate_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=255), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('log_id')
    )
    op.create_index(op.f('ix_audit_logs_aggregate_id'), 'audit_logs', ['aggregate_id'], unique=False)
    
    # Orders Service Tables
    op.create_table('orders_new',
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('customer_id', sa.String(length=255), nullable=False),
        sa.Column('store_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('total_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('order_id')
    )
    
    op.create_table('order_items_new',
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('product_id', sa.String(length=255), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price_minor', sa.BigInteger(), nullable=False),
        sa.Column('total_price_minor', sa.BigInteger(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders_new.order_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('item_id')
    )
    
    # Usage Service Tables
    op.create_table('usage_events_new',
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('meter_code', sa.String(length=100), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('event_id')
    )
    
    # Entry Service Tables
    op.create_table('entry_codes_new',
        sa.Column('code_id', sa.String(length=255), nullable=False),
        sa.Column('tenant_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('code_id'),
        sa.UniqueConstraint('code')
    )
    
    # Monitoring Service Tables
    op.create_table('service_health_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('service_name', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('last_check', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('alerts_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('service_name', sa.String(), nullable=False),
        sa.Column('alert_type', sa.String(), nullable=False),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Observability Service Tables
    op.create_table('metrics_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('metric_name', sa.String(), nullable=False),
        sa.Column('metric_type', sa.String(), nullable=False),
        sa.Column('value', sa.Numeric(), nullable=False),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('tenant_id', sa.String(), nullable=True),
        sa.Column('service_name', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('monitors_new',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('monitor_name', sa.String(), nullable=False),
        sa.Column('monitor_type', sa.String(), nullable=False),
        sa.Column('target_service', sa.String(), nullable=False),
        sa.Column('target_endpoint', sa.String(), nullable=False),
        sa.Column('check_interval_seconds', sa.Integer(), nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('threshold_value', sa.Numeric(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    """Drop all service tables"""
    op.drop_table('monitors_new')
    op.drop_table('metrics_new')
    op.drop_table('alerts_new')
    op.drop_table('service_health_new')
    op.drop_table('entry_codes_new')
    op.drop_table('usage_events_new')
    op.drop_table('order_items_new')
    op.drop_table('orders_new')
    op.drop_table('audit_logs')
    op.drop_table('outbox_events')
    op.drop_table('cost_centres')
    op.drop_table('vendors_new')
    op.drop_table('roles_new')
    op.drop_table('users_new')
    op.drop_table('stores_new')
    op.drop_table('sites_new')
    op.drop_table('tenants_new')
