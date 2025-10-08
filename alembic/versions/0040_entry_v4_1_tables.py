"""Entry V4.1 Tables

Revision ID: 0040_entry_v4_1_tables
Revises: 0039_payments_v4_1_tables
Create Date: 2025-01-07 20:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '0040_entry_v4_1_tables'
down_revision = '0039_payments_v4_1_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Create entry_codes_new
    op.create_table(
        'entry_codes_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sites.id'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stores.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('group_size', sa.Integer, default=1, nullable=False),
        sa.Column('provider', sa.String(50), default='internal', nullable=False),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('code', name='uq_entry_codes_new_code')
    )
    op.create_index('idx_entry_codes_new_tenant_id', 'entry_codes_new', ['tenant_id'])
    op.create_index('idx_entry_codes_new_user_id', 'entry_codes_new', ['user_id'])
    op.create_index('idx_entry_codes_new_store_id', 'entry_codes_new', ['store_id'])
    op.create_index('idx_entry_codes_new_expires_at', 'entry_codes_new', ['expires_at'])
    op.create_index('idx_entry_codes_new_consumed_at', 'entry_codes_new', ['consumed_at'])

    # Create zeroque_rails for entry providers (if not exists)
    op.execute("""
        INSERT INTO zeroque_rails (id, tenant_id, type, name, config, active, created_at, updated_at)
        SELECT 
            gen_random_uuid(),
            t.tenant_id,
            'entry' as type,
            'aifi' as name,
            '{"provider":"aifi","api_key":"demo_key","base_url":"https://api.aifi.io","entry_endpoint":"/entry-codes"}'::jsonb as config,
            true as active,
            now() as created_at,
            now() as updated_at
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM zeroque_rails zr 
            WHERE zr.tenant_id = t.tenant_id AND zr.type = 'entry' AND zr.name = 'aifi'
        )
    """)

    # Create outbox_events for entry events (if not exists)
    op.execute("""
        CREATE TABLE IF NOT EXISTS outbox_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(tenant_id),
            event_type VARCHAR(100) NOT NULL,
            event_data JSONB NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """)
    op.create_index('idx_outbox_events_tenant_id', 'outbox_events', ['tenant_id'])
    op.create_index('idx_outbox_events_status', 'outbox_events', ['status'])
    op.create_index('idx_outbox_events_event_type', 'outbox_events', ['event_type'])

    # Create audit_logs for entry operations (if not exists)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(tenant_id),
            user_id UUID REFERENCES users(id),
            action VARCHAR(50) NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            resource_id VARCHAR(100),
            details JSONB,
            ip_address INET,
            user_agent TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """)
    op.create_index('idx_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])
    op.create_index('idx_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('idx_audit_logs_resource_type', 'audit_logs', ['resource_type'])

    # RLS policies for entry_codes_new
    op.execute("""
        ALTER TABLE entry_codes_new ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS entry_codes_new_isolation_policy ON entry_codes_new;
        CREATE POLICY entry_codes_new_isolation_policy ON entry_codes_new
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)

    # RLS policies for outbox_events
    op.execute("""
        ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS outbox_events_isolation_policy ON outbox_events;
        CREATE POLICY outbox_events_isolation_policy ON outbox_events
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)

    # RLS policies for audit_logs
    op.execute("""
        ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS audit_logs_isolation_policy ON audit_logs;
        CREATE POLICY audit_logs_isolation_policy ON audit_logs
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)


def downgrade():
    # Revert RLS policies
    op.execute("ALTER TABLE entry_codes_new DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS entry_codes_new_isolation_policy ON entry_codes_new;")
    op.execute("ALTER TABLE outbox_events DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS outbox_events_isolation_policy ON outbox_events;")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS audit_logs_isolation_policy ON audit_logs;")

    # Drop new tables
    op.drop_table('entry_codes_new')
    # Note: Not dropping outbox_events and audit_logs as they might be used by other services
