"""store-specific products, pricing rules engine, and promotions

Revision ID: 0008_store_pricing
Revises: 0007_budgets_usage
Create Date: 2025-09-25 00:15:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0008_store_pricing'
down_revision = '0007_budgets_usage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            -- Store-specific products with base pricing
            CREATE TABLE IF NOT EXISTS store_products (
              id           BIGSERIAL PRIMARY KEY,
              store_id     TEXT NOT NULL,
              sku          TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              base_price_minor INTEGER NULL,
              currency     CHAR(3) NOT NULL DEFAULT 'GBP',
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL,
              UNIQUE (store_id, sku)
            );
            CREATE INDEX IF NOT EXISTS idx_store_products_store_id ON store_products(store_id);
            CREATE INDEX IF NOT EXISTS idx_store_products_sku ON store_products(sku);

            -- Pricing rules engine
            CREATE TABLE IF NOT EXISTS price_rules (
              id           BIGSERIAL PRIMARY KEY,
              name         TEXT NOT NULL,
              description  TEXT NULL,
              rule_type    TEXT NOT NULL, -- percentage|fixed|formula|override
              rule_config  JSONB NOT NULL, -- flexible config for different rule types
              priority     INTEGER NOT NULL DEFAULT 100, -- lower = higher priority
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              tenant_id    TEXT NULL,
              site_id      TEXT NULL,
              store_id     TEXT NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL
            );
            CREATE INDEX IF NOT EXISTS idx_price_rules_tenant_id ON price_rules(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_price_rules_site_id ON price_rules(site_id);
            CREATE INDEX IF NOT EXISTS idx_price_rules_store_id ON price_rules(store_id);

            -- Conditions for price rules
            CREATE TABLE IF NOT EXISTS price_rule_conditions (
              id           BIGSERIAL PRIMARY KEY,
              rule_id      BIGINT NOT NULL REFERENCES price_rules(id) ON DELETE CASCADE,
              condition_type TEXT NOT NULL, -- sku|category|user_role|time|quantity|etc
              condition_config JSONB NOT NULL, -- flexible condition config
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_price_rule_conditions_rule_id ON price_rule_conditions(rule_id);

            -- Promotions engine
            CREATE TABLE IF NOT EXISTS promotions (
              id           BIGSERIAL PRIMARY KEY,
              name         TEXT NOT NULL,
              description  TEXT NULL,
              promo_type   TEXT NOT NULL, -- discount|tax|bogo|bulk|etc
              promo_config JSONB NOT NULL, -- flexible promotion config
              priority     INTEGER NOT NULL DEFAULT 100,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              valid_from   TIMESTAMPTZ NULL,
              valid_until  TIMESTAMPTZ NULL,
              tenant_id    TEXT NULL,
              site_id      TEXT NULL,
              store_id     TEXT NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL
            );
            CREATE INDEX IF NOT EXISTS idx_promotions_tenant_id ON promotions(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_promotions_site_id ON promotions(site_id);
            CREATE INDEX IF NOT EXISTS idx_promotions_store_id ON promotions(store_id);

            -- Conditions for promotions
            CREATE TABLE IF NOT EXISTS promotion_conditions (
              id           BIGSERIAL PRIMARY KEY,
              promotion_id BIGINT NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
              condition_type TEXT NOT NULL, -- sku|category|user_role|min_amount|time|etc
              condition_config JSONB NOT NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_promotion_conditions_promotion_id ON promotion_conditions(promotion_id);

            -- Cache for calculated prices
            CREATE TABLE IF NOT EXISTS calculated_prices (
              id           BIGSERIAL PRIMARY KEY,
              store_id     TEXT NOT NULL,
              sku          TEXT NOT NULL,
              user_id      TEXT NULL,
              currency     CHAR(3) NOT NULL DEFAULT 'GBP',
              base_price_minor INTEGER NOT NULL,
              final_price_minor INTEGER NOT NULL,
              applied_rules JSONB NOT NULL DEFAULT '[]',
              applied_promotions JSONB NOT NULL DEFAULT '[]',
              calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              expires_at   TIMESTAMPTZ NULL,
              UNIQUE (store_id, sku, user_id, currency)
            );
            CREATE INDEX IF NOT EXISTS idx_calculated_prices_store_id ON calculated_prices(store_id);
            CREATE INDEX IF NOT EXISTS idx_calculated_prices_sku ON calculated_prices(sku);
            CREATE INDEX IF NOT EXISTS idx_calculated_prices_user_id ON calculated_prices(user_id);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS calculated_prices;
            DROP TABLE IF EXISTS promotion_conditions;
            DROP TABLE IF EXISTS promotions;
            DROP TABLE IF EXISTS price_rule_conditions;
            DROP TABLE IF EXISTS price_rules;
            DROP TABLE IF EXISTS store_products;
            """
        )
    )
