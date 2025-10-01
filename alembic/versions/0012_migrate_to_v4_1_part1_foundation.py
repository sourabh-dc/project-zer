"""migrate_to_v4.1_part1_foundation

Revision ID: 5172c46011dc
Revises: 0011_rls_policies
Create Date: 2025-09-30 14:32:21.716371+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5172c46011dc'
down_revision = '0011_rls_policies'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Step 1: Create Extensions
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"pg_trgm\";"))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"btree_gist\";"))
    
    # Step 2: Create Enums/Types
    op.execute(sa.text("""
        CREATE TYPE scope_type AS ENUM ('GLOBAL', 'TENANT', 'SITE', 'STORE', 'VENDOR');
    """))
    
    op.execute(sa.text("""
        CREATE TYPE owner_type AS ENUM ('TENANT', 'VENDOR');
    """))
    
    op.execute(sa.text("""
        CREATE TYPE price_scope AS ENUM ('TENANT', 'SITE', 'STORE', 'ROLE', 'VENDOR');
    """))
    
    op.execute(sa.text("""
        CREATE TYPE order_status AS ENUM ('pending', 'completed', 'cancelled', 'refunded', 'partially_refunded');
    """))
    
    op.execute(sa.text("""
        CREATE TYPE payout_status AS ENUM ('pending', 'queued', 'paid', 'failed', 'disputed');
    """))
    
    op.execute(sa.text("""
        CREATE TYPE movement_type AS ENUM ('receipt', 'sale', 'adjustment', 'transfer', 'return', 'shrink');
    """))
    
    # Step 3: Create New Tables - Organizational Structure
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS tenants_new (
            tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(200) NOT NULL,
            type TEXT NOT NULL DEFAULT 'customer' CHECK (type IN ('customer', 'marketplace', 'vendor_org', 'partner')),
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sites_new (
            site_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(200) NOT NULL,
            geo JSONB NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS tenant_sites (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants_new(tenant_id) ON DELETE CASCADE,
            site_id UUID NOT NULL REFERENCES sites_new(site_id) ON DELETE CASCADE,
            role_type TEXT NOT NULL DEFAULT 'manager',
            rights_expire_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, site_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS stores_new (
            store_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(200) NOT NULL,
            timezone TEXT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS site_stores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            site_id UUID NOT NULL REFERENCES sites_new(site_id) ON DELETE CASCADE,
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(site_id, store_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS tenant_store_admins (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants_new(tenant_id) ON DELETE CASCADE,
            store_id UUID NOT NULL REFERENCES stores_new(store_id) ON DELETE CASCADE,
            role_code TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(tenant_id, store_id, role_code)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants_new(tenant_id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NULL,
            rating NUMERIC(3,2) NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL,
            UNIQUE(tenant_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS vendor_onboarding (
            onboarding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vendor_id UUID NOT NULL REFERENCES vendors(vendor_id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            requirements JSONB NULL,
            approver_id UUID NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    # Step 4: Create User & RBAC Tables
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS users_new (
            user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) UNIQUE NOT NULL,
            display_name VARCHAR(200) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NULL
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS roles_new (
            role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(100) UNIQUE NOT NULL,
            description VARCHAR(200) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS role_assignments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users_new(user_id) ON DELETE CASCADE,
            role_id UUID NOT NULL REFERENCES roles_new(role_id) ON DELETE CASCADE,
            scope_type scope_type NOT NULL DEFAULT 'GLOBAL',
            scope_id UUID NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, role_id, scope_type, scope_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS permissions_new (
            permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT NULL,
            category VARCHAR(50) NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS role_permissions_new (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            role_id UUID NOT NULL REFERENCES roles_new(role_id) ON DELETE CASCADE,
            permission_id UUID NOT NULL REFERENCES permissions_new(permission_id) ON DELETE CASCADE,
            granted BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(role_id, permission_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS permission_grants (
            grant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            grantee_type TEXT NOT NULL CHECK (grantee_type IN ('user', 'role')),
            grantee_id UUID NOT NULL,
            permission_id UUID NOT NULL REFERENCES permissions_new(permission_id) ON DELETE CASCADE,
            scope_type scope_type NOT NULL,
            scope_id UUID NULL,
            priority SMALLINT NOT NULL DEFAULT 1000,
            is_granted BOOLEAN NOT NULL DEFAULT TRUE,
            granted_by UUID NOT NULL REFERENCES users_new(user_id),
            granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            UNIQUE(grantee_type, grantee_id, permission_id, scope_type, scope_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS permission_resolution_cache (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users_new(user_id) ON DELETE CASCADE,
            permission_id UUID NOT NULL REFERENCES permissions_new(permission_id) ON DELETE CASCADE,
            scope_type scope_type NOT NULL,
            scope_id UUID NOT NULL,
            is_granted BOOLEAN NOT NULL,
            resolution_path JSONB NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, permission_id, scope_type, scope_id)
        );
    """))
    
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_manager_links (
            user_id UUID NOT NULL REFERENCES users_new(user_id) ON DELETE CASCADE,
            manager_user_id UUID NOT NULL REFERENCES users_new(user_id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, manager_user_id)
        );
    """))


def downgrade() -> None:
    pass


