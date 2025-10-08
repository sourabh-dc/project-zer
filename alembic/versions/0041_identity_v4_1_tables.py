from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '0041_identity_v4_1_tables'
down_revision = '0040_entry_v4_1_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Create users_new table
    op.create_table(
        'users_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('primary_cost_centre_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cost_centres_new.cost_centre_id'), nullable=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'email', name='uq_users_new_tenant_email')
    )
    op.create_index('idx_users_new_tenant_id', 'users_new', ['tenant_id'])
    op.create_index('idx_users_new_email', 'users_new', ['email'])

    # Create roles_new table
    op.create_table(
        'roles_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('permissions', postgresql.JSONB, nullable=False),  # Array of permission strings
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_roles_new_tenant_name')
    )
    op.create_index('idx_roles_new_tenant_id', 'roles_new', ['tenant_id'])

    # Create role_assignments_new table
    op.create_table(
        'role_assignments_new',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users_new.id'), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('roles_new.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'user_id', 'role_id', name='uq_role_assignments_new_tenant_user_role')
    )
    op.create_index('idx_role_assignments_new_tenant_id', 'role_assignments_new', ['tenant_id'])
    op.create_index('idx_role_assignments_new_user_id', 'role_assignments_new', ['user_id'])
    op.create_index('idx_role_assignments_new_role_id', 'role_assignments_new', ['role_id'])

    # Create outbox_events table (if not exists from other services)
    op.create_table(
        'outbox_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', postgresql.JSONB, nullable=False),
        sa.Column('status', sa.String(50), default='pending', nullable=False),
        sa.Column('retry_count', sa.Integer, default=0, nullable=False),
        sa.Column('max_retries', sa.Integer, default=3, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    op.create_index('idx_outbox_events_tenant_id', 'outbox_events', ['tenant_id'])
    op.create_index('idx_outbox_events_status', 'outbox_events', ['status'])

    # Create audit_logs table (if not exists from other services)
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.tenant_id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users_new.id'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(100), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=True),
        sa.Column('details', postgresql.JSONB, nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    )
    op.create_index('idx_audit_logs_tenant_id', 'audit_logs', ['tenant_id'])
    op.create_index('idx_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_logs_action', 'audit_logs', ['action'])

    # RLS policies
    # For users_new
    op.execute("""
        ALTER TABLE users_new ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS users_new_isolation_policy ON users_new;
        CREATE POLICY users_new_isolation_policy ON users_new
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)
    
    # For roles_new
    op.execute("""
        ALTER TABLE roles_new ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS roles_new_isolation_policy ON roles_new;
        CREATE POLICY roles_new_isolation_policy ON roles_new
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)
    
    # For role_assignments_new
    op.execute("""
        ALTER TABLE role_assignments_new ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS role_assignments_new_isolation_policy ON role_assignments_new;
        CREATE POLICY role_assignments_new_isolation_policy ON role_assignments_new
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)
    
    # For outbox_events
    op.execute("""
        ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS outbox_events_isolation_policy ON outbox_events;
        CREATE POLICY outbox_events_isolation_policy ON outbox_events
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)
    
    # For audit_logs
    op.execute("""
        ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS audit_logs_isolation_policy ON audit_logs;
        CREATE POLICY audit_logs_isolation_policy ON audit_logs
        USING (tenant_id = (current_setting('app.tenant_id', TRUE)::uuid));
    """)

    # Data migration from legacy users table (if exists)
    op.execute("""
        INSERT INTO users_new (id, tenant_id, email, name, created_at, updated_at, metadata)
        SELECT 
            id,
            COALESCE(tenant_id, '550e8400-e29b-41d4-a716-446655440000'::uuid) as tenant_id,
            email,
            name,
            created_at,
            updated_at,
            metadata
        FROM users
        ON CONFLICT (id) DO NOTHING;
    """)


def downgrade():
    # Revert RLS policies
    op.execute("ALTER TABLE users_new DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS users_new_isolation_policy ON users_new;")
    op.execute("ALTER TABLE roles_new DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS roles_new_isolation_policy ON roles_new;")
    op.execute("ALTER TABLE role_assignments_new DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS role_assignments_new_isolation_policy ON role_assignments_new;")
    op.execute("ALTER TABLE outbox_events DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS outbox_events_isolation_policy ON outbox_events;")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS audit_logs_isolation_policy ON audit_logs;")

    # Drop tables
    op.drop_table('audit_logs')
    op.drop_table('outbox_events')
    op.drop_table('role_assignments_new')
    op.drop_table('roles_new')
    op.drop_table('users_new')
