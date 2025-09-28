"""idempotency keys + cv reviews + trade/stripe adjunct tables

Revision ID: 0004_idempotency_and_reviews
Revises: 0003_ledger_double_entry
Create Date: 2025-09-25 00:15:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0004_idempotency_and_reviews'
down_revision = '0003_ledger_double_entry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE TABLE IF NOT EXISTS idempotency_keys (
          id SERIAL PRIMARY KEY,
          scope VARCHAR(80) NOT NULL,
          request_id VARCHAR(120) NOT NULL,
          response JSONB NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE(scope, request_id)
        );

        CREATE TABLE IF NOT EXISTS cv_unknown_item_reviews (
          id SERIAL PRIMARY KEY,
          provider VARCHAR(40) NOT NULL,
          tenant_id VARCHAR(100) NOT NULL,
          site_id VARCHAR(100) NOT NULL,
          store_id VARCHAR(100) NOT NULL,
          external_sku VARCHAR(120) NOT NULL,
          name TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price_minor INTEGER NOT NULL,
          payload_json JSONB NOT NULL,
          status VARCHAR(20) NOT NULL DEFAULT 'pending',
          mapped_sku VARCHAR(120) NULL,
          notes TEXT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS stripe_events (
          id SERIAL PRIMARY KEY,
          event_id VARCHAR(120) UNIQUE NOT NULL,
          event_type VARCHAR(120) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS stripe_charges (
          id SERIAL PRIMARY KEY,
          tenant_id VARCHAR(100),
          site_id VARCHAR(100),
          order_id VARCHAR(100),
          payment_intent_id VARCHAR(120) UNIQUE,
          charge_id VARCHAR(120),
          amount_minor INTEGER,
          currency CHAR(3),
          status VARCHAR(40),
          receipt_url TEXT NULL,
          raw JSONB NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NULL
        );
        """
    ))


def downgrade() -> None:
    pass


