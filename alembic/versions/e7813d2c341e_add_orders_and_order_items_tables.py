"""add_orders_and_order_items_tables

Revision ID: e7813d2c341e
Revises: c2a02f699c83
Create Date: 2025-09-28 09:40:00.461808+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e7813d2c341e'
down_revision = 'c2a02f699c83'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS orders (
              order_id       BIGSERIAL PRIMARY KEY,
              tenant_id      TEXT NOT NULL,
              site_id        TEXT NOT NULL,
              store_id       TEXT NOT NULL,
              shopper_id     TEXT NOT NULL,
              total_minor    DECIMAL(10,2) NOT NULL,
              currency       CHAR(3) NOT NULL DEFAULT 'GBP',
              status         TEXT NOT NULL DEFAULT 'pending',
              occurred_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at     TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
              FOREIGN KEY (site_id) REFERENCES sites(site_id),
              FOREIGN KEY (store_id) REFERENCES stores(store_id),
              FOREIGN KEY (shopper_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
              id             BIGSERIAL PRIMARY KEY,
              order_id       BIGINT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
              sku            TEXT NOT NULL,
              name           TEXT NOT NULL,
              qty            INTEGER NOT NULL,
              price_minor    DECIMAL(10,2) NOT NULL,
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              FOREIGN KEY (sku) REFERENCES products(sku)
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_orders_tenant_id ON orders(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_orders_store_id ON orders(store_id);
            CREATE INDEX IF NOT EXISTS idx_orders_shopper_id ON orders(shopper_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_orders_occurred_at ON orders(occurred_at);
            CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
            CREATE INDEX IF NOT EXISTS idx_order_items_sku ON order_items(sku);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS order_items;
            DROP TABLE IF EXISTS orders;
            """
        )
    )


