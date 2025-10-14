"""Add Phase 1 & Phase 2 features: OAuth, Device Monitoring, Site Registry

Revision ID: phase1_phase2_features
Revises: 
Create Date: 2025-10-14

Phase 1: Identity & Access
- OAuth providers and sessions tables for SSO
- No changes to existing users/roles tables (bulk import uses existing schema)

Phase 2: Sites & Hardware
- Add device_metadata column to sites_new table
- Add devices, device_status_logs, and device_alerts tables for device monitoring

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = 'phase1_phase2_features'
down_revision = '0044_comprehensive_v4_1_tables'
branch_labels = None
depends_on = None


def upgrade():
    """Apply Phase 1 & Phase 2 schema changes"""
    
    # =============================================
    # PHASE 1: IDENTITY & ACCESS
    # =============================================
    
    # Create oauth_providers table
    op.create_table(
        'oauth_providers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('provider_type', sa.String(50), nullable=False),
        sa.Column('provider_name', sa.String(255), nullable=False),
        sa.Column('client_id', sa.String(500), nullable=False),
        sa.Column('client_secret', sa.String(500), nullable=False),
        sa.Column('tenant_domain', sa.String(255), nullable=True),
        sa.Column('discovery_url', sa.Text, nullable=True),
        sa.Column('scopes', JSONB, nullable=False, server_default='["openid", "profile", "email"]'),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('config_metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    op.create_index('idx_oauth_providers_tenant_id', 'oauth_providers', ['tenant_id'])
    
    # Create oauth_sessions table
    op.create_table(
        'oauth_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False),
        sa.Column('provider_id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),
        sa.Column('state', sa.String(500), nullable=False, index=True),
        sa.Column('code_verifier', sa.String(500), nullable=True),
        sa.Column('redirect_uri', sa.Text, nullable=False),
        sa.Column('external_user_id', sa.String(255), nullable=True),
        sa.Column('external_email', sa.String(255), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='initiated'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    op.create_index('idx_oauth_sessions_state', 'oauth_sessions', ['state'])
    op.create_index('idx_oauth_sessions_tenant_id', 'oauth_sessions', ['tenant_id'])
    
    # =============================================
    # PHASE 2: SITES & HARDWARE
    # =============================================
    
    # Add device_metadata column to sites_new table
    op.add_column('sites_new', sa.Column('device_metadata', JSONB, nullable=True))
    
    # Create devices table for device monitoring
    op.create_table(
        'devices',
        sa.Column('device_id', sa.String(100), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('site_id', UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('device_type', sa.String(50), nullable=False),
        sa.Column('device_name', sa.String(255), nullable=False),
        sa.Column('zone', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='online'),
        sa.Column('health_score', sa.Integer, nullable=True),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=True),
        sa.Column('device_metadata', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    op.create_index('idx_devices_tenant_id', 'devices', ['tenant_id'])
    op.create_index('idx_devices_site_id', 'devices', ['site_id'])
    op.create_index('idx_devices_status', 'devices', ['status'])
    
    # Create device_status_logs table
    op.create_table(
        'device_status_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('device_id', sa.String(100), nullable=False, index=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('health_score', sa.Integer, nullable=True),
        sa.Column('details', JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    op.create_index('idx_device_status_logs_device_id', 'device_status_logs', ['device_id'])
    op.create_index('idx_device_status_logs_created_at', 'device_status_logs', ['created_at'])
    
    # Create device_alerts table
    op.create_table(
        'device_alerts',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('device_id', sa.String(100), nullable=False, index=True),
        sa.Column('tenant_id', UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('alert_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='warning'),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('acknowledged_by', sa.String(255), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    op.create_index('idx_device_alerts_device_id', 'device_alerts', ['device_id'])
    op.create_index('idx_device_alerts_status', 'device_alerts', ['status'])
    op.create_index('idx_device_alerts_created_at', 'device_alerts', ['created_at'])


def downgrade():
    """Rollback Phase 1 & Phase 2 schema changes"""
    
    # =============================================
    # PHASE 2: SITES & HARDWARE (Rollback)
    # =============================================
    
    # Drop device monitoring tables
    op.drop_table('device_alerts')
    op.drop_table('device_status_logs')
    op.drop_table('devices')
    
    # Remove device_metadata column from sites_new
    op.drop_column('sites_new', 'device_metadata')
    
    # =============================================
    # PHASE 1: IDENTITY & ACCESS (Rollback)
    # =============================================
    
    # Drop OAuth tables
    op.drop_table('oauth_sessions')
    op.drop_table('oauth_providers')

