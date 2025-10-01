"""add_stripe_customers_table

Revision ID: a5bfe3447d51
Revises: 9bce609d78b4
Create Date: 2025-09-28 10:03:21.879114+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a5bfe3447d51'
down_revision = '9bce609d78b4'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS stripe_customers (
              id                 BIGSERIAL PRIMARY KEY,
              tenant_id          VARCHAR(100) NOT NULL UNIQUE,
              stripe_customer_id VARCHAR(100) NOT NULL,
              created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at         TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_stripe_customers_tenant_id ON stripe_customers(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_stripe_customers_stripe_customer_id ON stripe_customers(stripe_customer_id);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS stripe_customers;
            """
        )
    )


