"""budgets + usage tables

Revision ID: 0007_budgets_usage
Revises: 0006_prov_maps
Create Date: 2025-09-25 00:28:00

"""
from alembic import op
import sqlalchemy as sa

revision = '0007_budgets_usage'
down_revision = '0006_prov_maps'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        """
        CREATE TABLE IF NOT EXISTS cost_centres (
          cost_centre_id VARCHAR(100) PRIMARY KEY,
          tenant_id VARCHAR(100) NOT NULL,
          name VARCHAR(200) NOT NULL,
          manager_user_id VARCHAR(100) NULL
        );
        CREATE INDEX IF NOT EXISTS ix_cc_tenant ON cost_centres(tenant_id);

        CREATE TABLE IF NOT EXISTS budgets (
          budget_id VARCHAR(100) PRIMARY KEY,
          cost_centre_id VARCHAR(100) NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
          period VARCHAR(20) NOT NULL,
          currency CHAR(3) NOT NULL DEFAULT 'GBP',
          limit_minor BIGINT NOT NULL,
          spent_minor BIGINT NOT NULL DEFAULT 0,
          hard_block BOOLEAN NOT NULL DEFAULT TRUE
        );

        CREATE TABLE IF NOT EXISTS user_cost_centres (
          id SERIAL PRIMARY KEY,
          user_id VARCHAR(100) NOT NULL,
          cost_centre_id VARCHAR(100) NOT NULL REFERENCES cost_centres(cost_centre_id) ON DELETE CASCADE,
          UNIQUE(user_id, cost_centre_id)
        );

        CREATE TABLE IF NOT EXISTS usage_meters (
          id SERIAL PRIMARY KEY,
          code VARCHAR(100) UNIQUE NOT NULL,
          description VARCHAR(255) NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS usage_events (
          id SERIAL PRIMARY KEY,
          tenant_id VARCHAR(100) NOT NULL,
          site_id VARCHAR(100),
          store_id VARCHAR(100),
          meter_code VARCHAR(100) NOT NULL,
          subject_id VARCHAR(100),
          value INTEGER NOT NULL DEFAULT 1,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_usage_events_tenant ON usage_events(tenant_id);

        CREATE TABLE IF NOT EXISTS usage_aggregates_daily (
          id SERIAL PRIMARY KEY,
          day DATE NOT NULL,
          tenant_id VARCHAR(100) NOT NULL,
          site_id VARCHAR(100),
          store_id VARCHAR(100),
          meter_code VARCHAR(100) NOT NULL,
          value INTEGER NOT NULL DEFAULT 0,
          UNIQUE(day, tenant_id, site_id, store_id, meter_code)
        );
        """
    ))


def downgrade() -> None:
    pass


