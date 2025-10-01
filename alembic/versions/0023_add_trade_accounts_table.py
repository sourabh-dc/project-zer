"""add_trade_accounts_table

Revision ID: 9bce609d78b4
Revises: 04378856c4da
Create Date: 2025-09-28 09:56:46.651492+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9bce609d78b4'
down_revision = '04378856c4da'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS trade_accounts (
              id               BIGSERIAL PRIMARY KEY,
              tenant_id        VARCHAR(100) NOT NULL UNIQUE,
              ar_customer_code VARCHAR(100) NOT NULL,
              terms            VARCHAR(50) NOT NULL DEFAULT 'NET30',
              active           BOOLEAN NOT NULL DEFAULT TRUE,
              created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at       TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
            );

            -- Create index for better performance
            CREATE INDEX IF NOT EXISTS idx_trade_accounts_tenant_id ON trade_accounts(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_trade_accounts_active ON trade_accounts(active);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS trade_accounts;
            """
        )
    )


