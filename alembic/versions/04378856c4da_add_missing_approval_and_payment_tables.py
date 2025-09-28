"""add_missing_approval_and_payment_tables

Revision ID: 04378856c4da
Revises: e7813d2c341e
Create Date: 2025-09-28 09:40:23.284281+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '04378856c4da'
down_revision = 'e7813d2c341e'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS approval_rules (
              id             BIGSERIAL PRIMARY KEY,
              tenant_id      TEXT NOT NULL,
              cost_centre_id TEXT NOT NULL,
              rule_name      TEXT NOT NULL,
              rule_config    JSONB NOT NULL,
              active         BOOLEAN NOT NULL DEFAULT TRUE,
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at     TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
              FOREIGN KEY (cost_centre_id) REFERENCES cost_centres(cost_centre_id)
            );

            CREATE TABLE IF NOT EXISTS approval_requests (
              id             BIGSERIAL PRIMARY KEY,
              tenant_id      TEXT NOT NULL,
              cost_centre_id TEXT NOT NULL,
              user_scope_id  TEXT NULL,
              amount_minor   DECIMAL(10,2) NOT NULL,
              currency       CHAR(3) NOT NULL DEFAULT 'GBP',
              status         TEXT NOT NULL DEFAULT 'pending',
              reason         TEXT NULL,
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at     TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
              FOREIGN KEY (cost_centre_id) REFERENCES cost_centres(cost_centre_id)
            );

            CREATE TABLE IF NOT EXISTS payment_preferences (
              id             BIGSERIAL PRIMARY KEY,
              tenant_id      TEXT NOT NULL,
              method         TEXT NOT NULL,
              config         JSONB NULL,
              active         BOOLEAN NOT NULL DEFAULT TRUE,
              created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at     TIMESTAMPTZ NULL,
              FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
              UNIQUE (tenant_id, method)
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_approval_rules_tenant_id ON approval_rules(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_approval_rules_cost_centre_id ON approval_rules(cost_centre_id);
            CREATE INDEX IF NOT EXISTS idx_approval_requests_tenant_id ON approval_requests(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_approval_requests_cost_centre_id ON approval_requests(cost_centre_id);
            CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
            CREATE INDEX IF NOT EXISTS idx_payment_preferences_tenant_id ON payment_preferences(tenant_id);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS payment_preferences;
            DROP TABLE IF EXISTS approval_requests;
            DROP TABLE IF EXISTS approval_rules;
            """
        )
    )


