"""trade invoices tables

Revision ID: 0005_trade_invoices
Revises: 0004_idempotency_and_reviews
Create Date: 2025-09-25 00:18:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0005_trade_invoices'
down_revision = '0004_idempotency_and_reviews'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE TABLE IF NOT EXISTS trade_invoices (
          id VARCHAR(120) PRIMARY KEY,
          tenant_id VARCHAR(100) NOT NULL,
          site_id VARCHAR(100),
          order_id VARCHAR(100),
          amount_minor INTEGER NOT NULL,
          currency CHAR(3) NOT NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'draft',
          memo TEXT DEFAULT '',
          invoice_code TEXT NULL,
          exported_at TIMESTAMPTZ NULL,
          export_batch_id TEXT NULL,
          posted_at TIMESTAMPTZ NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NULL
        );

        CREATE TABLE IF NOT EXISTS trade_invoice_lines (
          id SERIAL PRIMARY KEY,
          invoice_id VARCHAR(120) NOT NULL,
          sku TEXT NOT NULL,
          qty INTEGER NOT NULL,
          unit_price_minor INTEGER NOT NULL,
          currency CHAR(3) NOT NULL,
          tax_minor INTEGER NOT NULL DEFAULT 0,
          tax_code TEXT NULL,
          FOREIGN KEY (invoice_id) REFERENCES trade_invoices(id) ON DELETE CASCADE
        );
        """
    ))


def downgrade() -> None:
    pass


