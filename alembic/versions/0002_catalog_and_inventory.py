"""catalog + inventory baseline

Revision ID: 0002_catalog_and_inventory
Revises: 0001_baseline
Create Date: 2025-09-25 00:10:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0002_catalog_and_inventory'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS products (
              sku          TEXT PRIMARY KEY,
              name         TEXT NOT NULL,
              description  TEXT NULL,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL
            );

            CREATE TABLE IF NOT EXISTS prices (
              id           BIGSERIAL PRIMARY KEY,
              sku          TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
              currency     CHAR(3) NOT NULL,
              unit_minor   INTEGER NOT NULL,
              active       BOOLEAN NOT NULL DEFAULT TRUE,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at   TIMESTAMPTZ NULL,
              UNIQUE (sku, currency)
            );

            CREATE TABLE IF NOT EXISTS inventory (
              store_id     TEXT NOT NULL,
              sku          TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
              qty          INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (store_id, sku)
            );

            CREATE TABLE IF NOT EXISTS inventory_movements (
              id           BIGSERIAL PRIMARY KEY,
              store_id     TEXT NOT NULL,
              sku          TEXT NOT NULL,
              delta        INTEGER NOT NULL,
              reason       TEXT NOT NULL,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            -- Guard columns if tables existed before
            ALTER TABLE products  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL;
            ALTER TABLE prices    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL;
            """
        )
    )


def downgrade() -> None:
    # Intentionally non-destructive for dev
    pass


