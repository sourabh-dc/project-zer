"""Enable Row Level Security for multi-tenant data isolation

Revision ID: 0011_rls_policies
Revises: 0010_enhanced_webhook_rbac
Create Date: 2025-01-27 10:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0011_rls_policies'
down_revision = '0010_enhanced_webhook_rbac'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Enable Row Level Security (RLS) on tenant-scoped tables.
    This provides defense-in-depth security by ensuring database-level tenant isolation.
    """
    
    # Create application role for RLS policies
    op.execute(sa.text("""
        -- Create application role if it doesn't exist
        DO $$ 
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zeroque_app') THEN
                CREATE ROLE zeroque_app;
            END IF;
        END
        $$;
        
        -- Grant necessary permissions to application role
        GRANT USAGE ON SCHEMA public TO zeroque_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO zeroque_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO zeroque_app;
        
        -- Set default privileges for future tables
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO zeroque_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO zeroque_app;
    """))
    
    # Enable RLS on core tenant-scoped tables
    core_tables = [
        'orders',
        'approval_requests', 
        'ledger_entries',
        'memberships',
        'site_subscriptions',
        'site_billing_accounts',
        'subscription_usage',
        'cost_centres',
        'trade_accounts',
        'trade_invoices',
        'stripe_customers',
        'stripe_charges',
        'usage_events',
        'notifications',
        'sites',
        'tenants'
    ]
    
    for table in core_tables:
        op.execute(sa.text(f"""
            -- Enable RLS on {table}
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            
            -- Create tenant isolation policy for {table}
            CREATE POLICY tenant_isolation_{table} ON {table}
            FOR ALL TO zeroque_app
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)
            );
        """))
    
    # Special policy for order_items (gets tenant context through orders)
    op.execute(sa.text("""
        -- Enable RLS on order_items
        ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
        
        -- Create foreign key tenant policy for order_items
        CREATE POLICY fk_tenant_isolation_order_items ON order_items
        FOR ALL TO zeroque_app
        USING (
            EXISTS (
                SELECT 1 FROM orders o 
                WHERE o.order_id = order_items.order_id
                AND o.tenant_id = current_setting('app.current_tenant_id', true)
            )
        );
    """))
    
    # Special policy for memberships table (user-tenant relationships)
    op.execute(sa.text("""
        CREATE POLICY membership_access ON memberships
        FOR ALL TO zeroque_app
        USING (
            -- Users can see their own memberships
            user_id = current_setting('app.current_user_id', true)
            OR
            -- Admins can see all memberships in their tenant
            current_setting('app.user_roles', true) LIKE '%admin%'
        );
    """))
    
    # Create function to set tenant context
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION set_tenant_context(
            p_tenant_id TEXT,
            p_user_id TEXT DEFAULT NULL,
            p_site_id TEXT DEFAULT NULL,
            p_store_id TEXT DEFAULT NULL,
            p_user_roles TEXT DEFAULT NULL
        ) RETURNS VOID AS $$
        BEGIN
            -- Set tenant context variables
            PERFORM set_config('app.current_tenant_id', p_tenant_id, false);
            
            IF p_user_id IS NOT NULL THEN
                PERFORM set_config('app.current_user_id', p_user_id, false);
            END IF;
            
            IF p_site_id IS NOT NULL THEN
                PERFORM set_config('app.current_site_id', p_site_id, false);
            END IF;
            
            IF p_store_id IS NOT NULL THEN
                PERFORM set_config('app.current_store_id', p_store_id, false);
            END IF;
            
            IF p_user_roles IS NOT NULL THEN
                PERFORM set_config('app.user_roles', p_user_roles, false);
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        
        -- Grant execute permission to application role
        GRANT EXECUTE ON FUNCTION set_tenant_context TO zeroque_app;
    """))
    
    # Create function to clear tenant context
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION clear_tenant_context() RETURNS VOID AS $$
        BEGIN
            -- Clear all tenant context variables
            PERFORM set_config('app.current_tenant_id', NULL, false);
            PERFORM set_config('app.current_user_id', NULL, false);
            PERFORM set_config('app.current_site_id', NULL, false);
            PERFORM set_config('app.current_store_id', NULL, false);
            PERFORM set_config('app.user_roles', NULL, false);
        END;
        $$ LANGUAGE plpgsql;
        
        -- Grant execute permission to application role
        GRANT EXECUTE ON FUNCTION clear_tenant_context TO zeroque_app;
    """))


def downgrade() -> None:
    """
    Disable Row Level Security and remove policies.
    WARNING: This will remove all tenant isolation at the database level!
    """
    
    # Drop all RLS policies
    core_tables = [
        'orders', 'approval_requests', 'ledger_entries', 'memberships',
        'site_subscriptions', 'site_billing_accounts', 'subscription_usage',
        'cost_centres', 'trade_accounts', 'trade_invoices', 'stripe_customers', 
        'stripe_charges', 'usage_events', 'notifications', 'sites', 'tenants'
    ]
    
    for table in core_tables:
        op.execute(sa.text(f"""
            DROP POLICY IF EXISTS tenant_isolation_{table} ON {table};
        """))
    
    # Drop special policies
    op.execute(sa.text("""
        DROP POLICY IF EXISTS fk_tenant_isolation_order_items ON order_items;
        DROP POLICY IF EXISTS membership_access ON memberships;
    """))
    
    # Disable RLS on all tables
    all_tables = core_tables + ['order_items']
    for table in all_tables:
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"))
    
    # Drop functions
    op.execute(sa.text("""
        DROP FUNCTION IF EXISTS set_tenant_context(TEXT, TEXT, TEXT, TEXT, TEXT);
        DROP FUNCTION IF EXISTS clear_tenant_context();
    """))
    
    # Drop application role (optional - might be used by other parts)
    # op.execute(sa.text("DROP ROLE IF EXISTS zeroque_app;"))