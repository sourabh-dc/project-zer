"""site-level subscriptions with plans, features, and billing

Revision ID: 0009_site_subscriptions
Revises: 0008_store_pricing
Create Date: 2025-09-25 00:20:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0009_site_subscriptions'
down_revision = '0008_store_pricing'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            -- Subscription plans with pricing
            CREATE TABLE IF NOT EXISTS subscription_plans (
              id           BIGSERIAL PRIMARY KEY,
              code         TEXT NOT NULL UNIQUE,
              name         TEXT NOT NULL,
              description  TEXT NULL,
              price_yearly_minor INTEGER NOT NULL,
              currency     CHAR(3) NOT NULL DEFAULT 'GBP',
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL
            );
            CREATE INDEX IF NOT EXISTS idx_subscription_plans_code ON subscription_plans(code);

            -- Features table
            CREATE TABLE IF NOT EXISTS features (
              id           BIGSERIAL PRIMARY KEY,
              code         TEXT NOT NULL UNIQUE,
              name         TEXT NOT NULL,
              description  TEXT NULL,
              category     TEXT NULL,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_features_code ON features(code);

            -- Plan features mapping table
            CREATE TABLE IF NOT EXISTS plan_features (
              id           BIGSERIAL PRIMARY KEY,
              plan_code    TEXT NOT NULL,
              feature_code TEXT NOT NULL,
              enabled      BOOLEAN NOT NULL DEFAULT TRUE,
              limits       JSONB NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE (plan_code, feature_code)
            );
            CREATE INDEX IF NOT EXISTS idx_plan_features_plan_code ON plan_features(plan_code);
            CREATE INDEX IF NOT EXISTS idx_plan_features_feature_code ON plan_features(feature_code);

            -- Site-level subscriptions
            CREATE TABLE IF NOT EXISTS site_subscriptions (
              id                   BIGSERIAL PRIMARY KEY,
              tenant_id            TEXT NOT NULL,
              site_id              TEXT NOT NULL,
              plan_code            TEXT NOT NULL REFERENCES subscription_plans(code),
              payment_method       TEXT NOT NULL,
              status               TEXT NOT NULL DEFAULT 'active',
              external_id          TEXT NOT NULL,
              current_period_start TIMESTAMPTZ NULL,
              current_period_end   TIMESTAMPTZ NULL,
              trial_end            TIMESTAMPTZ NULL,
              canceled_at          TIMESTAMPTZ NULL,
              created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at           TIMESTAMPTZ NULL,
              UNIQUE (tenant_id, site_id)
            );
            CREATE INDEX IF NOT EXISTS idx_site_subscriptions_tenant_id ON site_subscriptions(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_site_subscriptions_site_id ON site_subscriptions(site_id);
            CREATE INDEX IF NOT EXISTS idx_site_subscriptions_plan_code ON site_subscriptions(plan_code);
            CREATE INDEX IF NOT EXISTS idx_site_subscriptions_external_id ON site_subscriptions(external_id);

            -- Billing accounts for sites
            CREATE TABLE IF NOT EXISTS site_billing_accounts (
              id             BIGSERIAL PRIMARY KEY,
              tenant_id      TEXT NOT NULL,
              site_id        TEXT NOT NULL,
              payment_method TEXT NOT NULL,
              external_id    TEXT NOT NULL,
              active         BOOLEAN NOT NULL DEFAULT TRUE,
              metadata       JSONB NULL,
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at     TIMESTAMPTZ NULL,
              UNIQUE (tenant_id, site_id, payment_method)
            );
            CREATE INDEX IF NOT EXISTS idx_site_billing_accounts_tenant_id ON site_billing_accounts(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_site_billing_accounts_site_id ON site_billing_accounts(site_id);
            CREATE INDEX IF NOT EXISTS idx_site_billing_accounts_external_id ON site_billing_accounts(external_id);

            -- Track usage against subscription limits
            CREATE TABLE IF NOT EXISTS subscription_usage (
              id           BIGSERIAL PRIMARY KEY,
              tenant_id    TEXT NOT NULL,
              site_id      TEXT NOT NULL,
              feature_code TEXT NOT NULL,
              usage_type   TEXT NOT NULL,
              usage_count  INTEGER NOT NULL DEFAULT 0,
              period_start TIMESTAMPTZ NOT NULL,
              period_end   TIMESTAMPTZ NOT NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL,
              UNIQUE (tenant_id, site_id, feature_code, usage_type, period_start)
            );
            CREATE INDEX IF NOT EXISTS idx_subscription_usage_tenant_id ON subscription_usage(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_subscription_usage_site_id ON subscription_usage(site_id);
            CREATE INDEX IF NOT EXISTS idx_subscription_usage_feature_code ON subscription_usage(feature_code);
            CREATE INDEX IF NOT EXISTS idx_subscription_usage_period_start ON subscription_usage(period_start);

            -- Insert default subscription plans
            INSERT INTO subscription_plans (code, name, description, price_yearly_minor, currency) VALUES
            ('core', 'Core Plan', 'Basic features for small teams', 100000000, 'GBP'),
            ('pro', 'Pro Plan', 'Advanced features for growing businesses', 200000000, 'GBP'),
            ('enterprise', 'Enterprise Plan', 'Full features for large organizations', 500000000, 'GBP')
            ON CONFLICT (code) DO NOTHING;

            -- Insert default features
            INSERT INTO features (code, name, description, category) VALUES
            ('basic_pricing', 'Basic Pricing', 'Standard product pricing', 'pricing'),
            ('advanced_pricing', 'Advanced Pricing', 'Store-specific pricing and rules engine', 'pricing'),
            ('bulk_orders', 'Bulk Orders', 'Process multiple orders efficiently', 'orders'),
            ('analytics_basic', 'Basic Analytics', 'Basic reporting and analytics', 'analytics'),
            ('analytics_advanced', 'Advanced Analytics', 'Advanced reporting with custom metrics', 'analytics'),
            ('api_access', 'API Access', 'REST API access', 'integration'),
            ('webhook_support', 'Webhook Support', 'Real-time webhook notifications', 'integration'),
            ('multi_store', 'Multi-Store', 'Support for multiple stores per site', 'stores'),
            ('user_management', 'User Management', 'Advanced user and role management', 'users'),
            ('custom_branding', 'Custom Branding', 'White-label and custom branding', 'branding')
            ON CONFLICT (code) DO NOTHING;

            -- Assign features to plans
            INSERT INTO plan_features (plan_code, feature_code, enabled, limits) VALUES
            -- Core Plan features
            ('core', 'basic_pricing', true, '{"max_stores": 1, "max_users": 10}'),
            ('core', 'bulk_orders', true, '{"max_orders_per_day": 100}'),
            ('core', 'analytics_basic', true, '{}'),
            ('core', 'api_access', true, '{"rate_limit": 1000}'),
            ('core', 'multi_store', false, '{}'),
            ('core', 'user_management', true, '{"max_roles": 3}'),
            
            -- Pro Plan features (includes all Core features)
            ('pro', 'basic_pricing', true, '{"max_stores": 5, "max_users": 50}'),
            ('pro', 'advanced_pricing', true, '{"max_rules": 20, "max_promotions": 10}'),
            ('pro', 'bulk_orders', true, '{"max_orders_per_day": 1000}'),
            ('pro', 'analytics_basic', true, '{}'),
            ('pro', 'analytics_advanced', true, '{}'),
            ('pro', 'api_access', true, '{"rate_limit": 10000}'),
            ('pro', 'webhook_support', true, '{"max_webhooks": 5}'),
            ('pro', 'multi_store', true, '{"max_stores": 5}'),
            ('pro', 'user_management', true, '{"max_roles": 10}'),
            
            -- Enterprise Plan features (includes all Pro features)
            ('enterprise', 'basic_pricing', true, '{"max_stores": 100, "max_users": 1000}'),
            ('enterprise', 'advanced_pricing', true, '{"max_rules": 100, "max_promotions": 50}'),
            ('enterprise', 'bulk_orders', true, '{"max_orders_per_day": 10000}'),
            ('enterprise', 'analytics_basic', true, '{}'),
            ('enterprise', 'analytics_advanced', true, '{}'),
            ('enterprise', 'api_access', true, '{"rate_limit": 100000}'),
            ('enterprise', 'webhook_support', true, '{"max_webhooks": 50}'),
            ('enterprise', 'multi_store', true, '{"max_stores": 100}'),
            ('enterprise', 'user_management', true, '{"max_roles": 50}'),
            ('enterprise', 'custom_branding', true, '{}')
            ON CONFLICT (plan_code, feature_code) DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS subscription_usage;
            DROP TABLE IF EXISTS site_billing_accounts;
            DROP TABLE IF EXISTS site_subscriptions;
            DROP TABLE IF EXISTS plan_features;
            DROP TABLE IF EXISTS features;
            DROP TABLE IF EXISTS subscription_plans;
            """
        )
    )
