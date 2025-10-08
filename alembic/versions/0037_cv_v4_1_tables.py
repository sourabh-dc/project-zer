"""CV v4.1 Architecture Tables

Revision ID: 0037_cv_v4_1_tables
Revises: 0036_fix_database_schema_v4_1
Create Date: 2025-10-07 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0037_cv_v4_1_tables'
down_revision = '0036_fix_database_schema_v4_1'
branch_labels = None
depends_on = None


def upgrade():
    """Add CV v4.1 architecture tables"""
    
    # Create zeroque_rails table for CV configuration
    op.create_table('zeroque_rails',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),  # 'cv', 'payment', etc.
        sa.Column('name', sa.String(100), nullable=False),  # 'aifi', 'stripe', etc.
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('tenant_id', 'type', 'name', name='uq_zeroque_rails_tenant_type_name')
    )
    
    # Create provider_mappings table for external ID mapping
    op.create_table('provider_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(50), nullable=False),  # 'aifi', 'stripe', etc.
        sa.Column('entity_type', sa.String(50), nullable=False),  # 'user', 'store', 'product', etc.
        sa.Column('local_id', sa.String(255), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('provider', 'entity_type', 'local_id', name='uq_provider_mappings_provider_entity_local'),
        sa.UniqueConstraint('provider', 'entity_type', 'external_id', name='uq_provider_mappings_provider_entity_external')
    )
    
    # Create cv_unknown_item_reviews table
    op.create_table('cv_unknown_item_reviews',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('site_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('provider', sa.String(50), nullable=False),
        sa.Column('external_sku', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False),
        sa.Column('price_minor', sa.Integer(), nullable=False),
        sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),  # 'pending', 'resolved', 'ignored'
        sa.Column('mapped_sku', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('resolved_by', sa.String(255), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.site_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['store_id'], ['stores.store_id'], ondelete='CASCADE')
    )
    
    # Create outbox_events table for reliable event publishing
    op.create_table('outbox_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),  # 'pending', 'sent', 'failed'
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=False, default=3),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], ondelete='CASCADE')
    )
    
    # Create audit_logs table for operations tracking
    op.create_table('audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='SET NULL')
    )
    
    # Create indexes for performance
    op.create_index('idx_zeroque_rails_tenant_type', 'zeroque_rails', ['tenant_id', 'type'])
    op.create_index('idx_zeroque_rails_active', 'zeroque_rails', ['active'])
    
    op.create_index('idx_provider_mappings_tenant_provider', 'provider_mappings', ['tenant_id', 'provider'])
    op.create_index('idx_provider_mappings_entity_type', 'provider_mappings', ['entity_type'])
    op.create_index('idx_provider_mappings_local_id', 'provider_mappings', ['local_id'])
    op.create_index('idx_provider_mappings_external_id', 'provider_mappings', ['external_id'])
    
    op.create_index('idx_cv_unknown_item_reviews_tenant_status', 'cv_unknown_item_reviews', ['tenant_id', 'status'])
    op.create_index('idx_cv_unknown_item_reviews_provider', 'cv_unknown_item_reviews', ['provider'])
    op.create_index('idx_cv_unknown_item_reviews_created_at', 'cv_unknown_item_reviews', ['created_at'])
    
    op.create_index('idx_outbox_events_status_retry', 'outbox_events', ['status', 'next_retry_at'])
    op.create_index('idx_outbox_events_tenant_event_type', 'outbox_events', ['tenant_id', 'event_type'])
    op.create_index('idx_outbox_events_created_at', 'outbox_events', ['created_at'])
    
    op.create_index('idx_audit_logs_tenant_action', 'audit_logs', ['tenant_id', 'action'])
    op.create_index('idx_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('idx_audit_logs_user_created', 'audit_logs', ['user_id', 'created_at'])
    
    # Enable RLS on all tables
    op.execute('ALTER TABLE zeroque_rails ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE provider_mappings ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE cv_unknown_item_reviews ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY')
    
    # Create RLS policies
    # Zeroque Rails policies
    op.execute("""
        CREATE POLICY zeroque_rails_tenant_isolation ON zeroque_rails
        FOR ALL TO authenticated
        USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    
    # Provider Mappings policies
    op.execute("""
        CREATE POLICY provider_mappings_tenant_isolation ON provider_mappings
        FOR ALL TO authenticated
        USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    
    # CV Unknown Item Reviews policies
    op.execute("""
        CREATE POLICY cv_unknown_item_reviews_tenant_isolation ON cv_unknown_item_reviews
        FOR ALL TO authenticated
        USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    
    # Outbox Events policies
    op.execute("""
        CREATE POLICY outbox_events_tenant_isolation ON outbox_events
        FOR ALL TO authenticated
        USING (tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    
    # Audit Logs policies
    op.execute("""
        CREATE POLICY audit_logs_tenant_isolation ON audit_logs
        FOR ALL TO authenticated
        USING (tenant_id IS NULL OR tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)


def downgrade():
    """Remove CV v4.1 architecture tables"""
    
    # Drop indexes
    op.drop_index('idx_audit_logs_user_created', 'audit_logs')
    op.drop_index('idx_audit_logs_resource', 'audit_logs')
    op.drop_index('idx_audit_logs_tenant_action', 'audit_logs')
    
    op.drop_index('idx_outbox_events_created_at', 'outbox_events')
    op.drop_index('idx_outbox_events_tenant_event_type', 'outbox_events')
    op.drop_index('idx_outbox_events_status_retry', 'outbox_events')
    
    op.drop_index('idx_cv_unknown_item_reviews_created_at', 'cv_unknown_item_reviews')
    op.drop_index('idx_cv_unknown_item_reviews_provider', 'cv_unknown_item_reviews')
    op.drop_index('idx_cv_unknown_item_reviews_tenant_status', 'cv_unknown_item_reviews')
    
    op.drop_index('idx_provider_mappings_external_id', 'provider_mappings')
    op.drop_index('idx_provider_mappings_local_id', 'provider_mappings')
    op.drop_index('idx_provider_mappings_entity_type', 'provider_mappings')
    op.drop_index('idx_provider_mappings_tenant_provider', 'provider_mappings')
    
    op.drop_index('idx_zeroque_rails_active', 'zeroque_rails')
    op.drop_index('idx_zeroque_rails_tenant_type', 'zeroque_rails')
    
    # Drop tables
    op.drop_table('audit_logs')
    op.drop_table('outbox_events')
    op.drop_table('cv_unknown_item_reviews')
    op.drop_table('provider_mappings')
    op.drop_table('zeroque_rails')
