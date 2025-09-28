"""enhanced webhook processing and RBAC improvements

Revision ID: 0010_enhanced_webhook_rbac
Revises: 0009_site_subscriptions
Create Date: 2025-09-25 00:30:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0010_enhanced_webhook_rbac'
down_revision = '0009_site_subscriptions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            -- Webhook processing queue
            CREATE TABLE IF NOT EXISTS webhook_messages (
              id           TEXT PRIMARY KEY,
              payload      JSONB NOT NULL,
              status       TEXT NOT NULL DEFAULT 'pending',
              retry_count  INTEGER NOT NULL DEFAULT 0,
              max_retries  INTEGER NOT NULL DEFAULT 3,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL,
              error_message TEXT NULL,
              processing_attempts JSONB NULL
            );
            CREATE INDEX IF NOT EXISTS idx_webhook_messages_status ON webhook_messages(status);
            CREATE INDEX IF NOT EXISTS idx_webhook_messages_created_at ON webhook_messages(created_at);

            -- Enhanced RBAC permissions
            CREATE TABLE IF NOT EXISTS permissions (
              id           BIGSERIAL PRIMARY KEY,
              code         TEXT NOT NULL UNIQUE,
              name         TEXT NOT NULL,
              description  TEXT NULL,
              category     TEXT NULL,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_permissions_code ON permissions(code);

            -- Role permissions mapping
            CREATE TABLE IF NOT EXISTS role_permissions (
              id           BIGSERIAL PRIMARY KEY,
              role_code    TEXT NOT NULL,
              permission_code TEXT NOT NULL,
              granted      BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (role_code, permission_code)
            );
            CREATE INDEX IF NOT EXISTS idx_role_permissions_role_code ON role_permissions(role_code);
            CREATE INDEX IF NOT EXISTS idx_role_permissions_permission_code ON role_permissions(permission_code);

            -- Product normalization cache
            CREATE TABLE IF NOT EXISTS product_normalization_cache (
              id           BIGSERIAL PRIMARY KEY,
              external_id  TEXT NOT NULL,
              provider     TEXT NOT NULL,
              normalized_data JSONB NOT NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL,
              UNIQUE (external_id, provider)
            );
            CREATE INDEX IF NOT EXISTS idx_product_normalization_external_id ON product_normalization_cache(external_id);
            CREATE INDEX IF NOT EXISTS idx_product_normalization_provider ON product_normalization_cache(provider);

            -- Price calculation hooks
            CREATE TABLE IF NOT EXISTS price_hooks (
              id           BIGSERIAL PRIMARY KEY,
              hook_type    TEXT NOT NULL,
              trigger_event TEXT NOT NULL,
              target_service TEXT NOT NULL,
              target_endpoint TEXT NOT NULL,
              config       JSONB NULL,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_price_hooks_hook_type ON price_hooks(hook_type);
            CREATE INDEX IF NOT EXISTS idx_price_hooks_trigger_event ON price_hooks(trigger_event);

            -- Insert default permissions
            INSERT INTO permissions (code, name, description, category) VALUES
            ('read_tenant', 'Read Tenant', 'Read tenant information', 'tenant'),
            ('write_tenant', 'Write Tenant', 'Modify tenant information', 'tenant'),
            ('read_site', 'Read Site', 'Read site information', 'site'),
            ('write_site', 'Write Site', 'Modify site information', 'site'),
            ('read_store', 'Read Store', 'Read store information', 'store'),
            ('write_store', 'Write Store', 'Modify store information', 'store'),
            ('read_users', 'Read Users', 'Read user information', 'users'),
            ('write_users', 'Write Users', 'Modify user information', 'users'),
            ('read_pricing', 'Read Pricing', 'Read pricing information', 'pricing'),
            ('write_pricing', 'Write Pricing', 'Modify pricing information', 'pricing'),
            ('read_orders', 'Read Orders', 'Read order information', 'orders'),
            ('write_orders', 'Write Orders', 'Modify order information', 'orders'),
            ('read_budget', 'Read Budget', 'Read budget information', 'budget'),
            ('write_budget', 'Write Budget', 'Modify budget information', 'budget'),
            ('read_subscriptions', 'Read Subscriptions', 'Read subscription information', 'subscriptions'),
            ('write_subscriptions', 'Write Subscriptions', 'Modify subscription information', 'subscriptions'),
            ('read_analytics', 'Read Analytics', 'Read analytics and reports', 'analytics'),
            ('write_analytics', 'Write Analytics', 'Modify analytics and reports', 'analytics')
            ON CONFLICT (code) DO NOTHING;

            -- Assign permissions to roles
            INSERT INTO role_permissions (role_code, permission_code, granted) VALUES
            -- Admin role - all permissions
            ('admin', 'read_tenant', true),
            ('admin', 'write_tenant', true),
            ('admin', 'read_site', true),
            ('admin', 'write_site', true),
            ('admin', 'read_store', true),
            ('admin', 'write_store', true),
            ('admin', 'read_users', true),
            ('admin', 'write_users', true),
            ('admin', 'read_pricing', true),
            ('admin', 'write_pricing', true),
            ('admin', 'read_orders', true),
            ('admin', 'write_orders', true),
            ('admin', 'read_budget', true),
            ('admin', 'write_budget', true),
            ('admin', 'read_subscriptions', true),
            ('admin', 'write_subscriptions', true),
            ('admin', 'read_analytics', true),
            ('admin', 'write_analytics', true),
            
            -- Manager role - most permissions except tenant/subscription management
            ('manager', 'read_tenant', true),
            ('manager', 'read_site', true),
            ('manager', 'write_site', true),
            ('manager', 'read_store', true),
            ('manager', 'write_store', true),
            ('manager', 'read_users', true),
            ('manager', 'read_pricing', true),
            ('manager', 'write_pricing', true),
            ('manager', 'read_orders', true),
            ('manager', 'write_orders', true),
            ('manager', 'read_budget', true),
            ('manager', 'read_analytics', true),
            
            -- Employee role - limited permissions
            ('employee', 'read_store', true),
            ('employee', 'read_orders', true),
            ('employee', 'write_orders', true)
            ON CONFLICT (role_code, permission_code) DO NOTHING;

            -- Insert default price hooks
            INSERT INTO price_hooks (hook_type, trigger_event, target_service, target_endpoint, config) VALUES
            ('product_created', 'product.created', 'pricing', '/pricing/calculate', '{"force_recalculate": true}'),
            ('product_updated', 'product.updated', 'pricing', '/pricing/calculate', '{"force_recalculate": true}'),
            ('inventory_updated', 'inventory.updated', 'pricing', '/pricing/calculate', '{"force_recalculate": false}')
            ON CONFLICT DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS price_hooks;
            DROP TABLE IF EXISTS product_normalization_cache;
            DROP TABLE IF EXISTS role_permissions;
            DROP TABLE IF EXISTS permissions;
            DROP TABLE IF EXISTS webhook_messages;
            """
        )
    )
