from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '0042_events_v4_1_tables'
down_revision = '0041_identity_v4_1_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Create events_new table
    op.create_table(
        'events_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(50), default='pending', nullable=False), # pending, published, failed
        sa.Column('retry_count', sa.Integer, default=0, nullable=False),
        sa.Column('max_retries', sa.Integer, default=3, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('idx_events_new_tenant_id', 'events_new', ['tenant_id'])
    op.create_index('idx_events_new_event_type', 'events_new', ['event_type'])
    op.create_index('idx_events_new_status', 'events_new', ['status'])
    op.create_index('idx_events_new_created_at', 'events_new', ['created_at'])
    op.create_index('idx_events_new_tenant_status_created_at', 'events_new', ['tenant_id', 'status', 'created_at'])

    # Create event_subscriptions table for managing event subscriptions
    op.create_table(
        'event_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('service_name', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('queue_name', sa.String(100), nullable=False),
        sa.Column('active', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'service_name', 'event_type', name='uq_event_subscription_tenant_service_event')
    )
    op.create_index('idx_event_subscriptions_tenant_id', 'event_subscriptions', ['tenant_id'])
    op.create_index('idx_event_subscriptions_service_name', 'event_subscriptions', ['service_name'])

    # Create event_metrics table for monitoring
    op.create_table(
        'event_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('metric_type', sa.String(50), nullable=False), # publish, consume, failure, latency
        sa.Column('metric_value', sa.Float, nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('metadata', postgresql.JSONB, nullable=True)
    )
    op.create_index('idx_event_metrics_tenant_id', 'event_metrics', ['tenant_id'])
    op.create_index('idx_event_metrics_event_type', 'event_metrics', ['event_type'])
    op.create_index('idx_event_metrics_timestamp', 'event_metrics', ['timestamp'])

    # Add zeroque_rails for event service configuration if not exists
    # (This might already exist from other services, so we check first)
    op.execute("""
        CREATE TABLE IF NOT EXISTS zeroque_rails (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            type VARCHAR(50) NOT NULL,
            name VARCHAR(100) NOT NULL,
            config JSONB NOT NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE(tenant_id, type, name)
        );
    """)

    # RLS Policies
    op.execute("""
        ALTER TABLE events_new ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS events_new_isolation_policy ON events_new;
        CREATE POLICY events_new_isolation_policy ON events_new
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));

        ALTER TABLE event_subscriptions ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS event_subscriptions_isolation_policy ON event_subscriptions;
        CREATE POLICY event_subscriptions_isolation_policy ON event_subscriptions
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));

        ALTER TABLE event_metrics ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS event_metrics_isolation_policy ON event_metrics;
        CREATE POLICY event_metrics_isolation_policy ON event_metrics
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));

        ALTER TABLE zeroque_rails ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS zeroque_rails_isolation_policy ON zeroque_rails;
        CREATE POLICY zeroque_rails_isolation_policy ON zeroque_rails
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)

    # Data migration from Redis Streams (if any events exist)
    # This would typically involve reading from Redis and inserting into events_new
    # For now, we'll create a placeholder comment
    op.execute("""
        -- Note: If migrating from Redis Streams, add migration logic here
        -- to read existing events and insert into events_new table
    """)


def downgrade():
    # Revert RLS policies
    op.execute("ALTER TABLE events_new DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS events_new_isolation_policy ON events_new;")
    op.execute("ALTER TABLE event_subscriptions DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS event_subscriptions_isolation_policy ON event_subscriptions;")
    op.execute("ALTER TABLE event_metrics DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS event_metrics_isolation_policy ON event_metrics;")
    op.execute("ALTER TABLE zeroque_rails DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS zeroque_rails_isolation_policy ON zeroque_rails;")

    # Drop new tables
    op.drop_table('event_metrics')
    op.drop_table('event_subscriptions')
    op.drop_table('events_new')
    # Note: We don't drop zeroque_rails as it's used by other services
