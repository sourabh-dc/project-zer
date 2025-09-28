"""add_subscriptions_table

Revision ID: cbfa19c43658
Revises: 9e442d97bdd6
Create Date: 2025-09-28 10:23:28.855427+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cbfa19c43658'
down_revision = '9e442d97bdd6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
              id                 BIGSERIAL PRIMARY KEY,
              tenant_id          VARCHAR(100) NOT NULL,
              plan_code          VARCHAR(50) NOT NULL,
              provider           VARCHAR(20) NOT NULL,
              status             VARCHAR(50) NOT NULL DEFAULT 'active',
              external_id        VARCHAR(100) NOT NULL,
              created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at         TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant_id ON subscriptions(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_plan_code ON subscriptions(plan_code);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_external_id ON subscriptions(external_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS subscriptions;
            """
        )
    )


