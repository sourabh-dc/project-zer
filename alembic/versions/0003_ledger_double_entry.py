"""ledger double-entry columns

Revision ID: 0003_ledger_double_entry
Revises: 0002_catalog_and_inventory
Create Date: 2025-09-25 00:12:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0003_ledger_double_entry'
down_revision = '0002_catalog_and_inventory'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ledger_entries table if it doesn't exist
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
              id           BIGSERIAL PRIMARY KEY,
              tenant_id    TEXT NOT NULL,
              site_id      TEXT,
              store_id     TEXT,
              account      VARCHAR(40),
              entry_type   VARCHAR(10) DEFAULT 'debit',
              amount_minor INTEGER NOT NULL,
              currency     CHAR(3) NOT NULL,
              description  TEXT,
              reference_id TEXT,
              created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )


def downgrade() -> None:
    pass


