"""add_notification_deliveries_table

Revision ID: 9e442d97bdd6
Revises: 721371ee26d5
Create Date: 2025-09-28 10:23:11.535376+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9e442d97bdd6'
down_revision = '721371ee26d5'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS notification_deliveries (
              id                 BIGSERIAL PRIMARY KEY,
              channel            TEXT NOT NULL,
              tenant_id          TEXT NULL,
              subject            TEXT NULL,
              payload            JSONB NOT NULL,
              to_addr            TEXT NULL,
              url                TEXT NULL,
              headers            JSONB NULL,
              status             TEXT NOT NULL DEFAULT 'queued',
              attempts           INTEGER NOT NULL DEFAULT 0,
              next_attempt_at    TIMESTAMPTZ DEFAULT NOW(),
              error              TEXT NULL,
              created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at         TIMESTAMPTZ NULL
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_notification_deliveries_status_next ON notification_deliveries(status, next_attempt_at);
            CREATE INDEX IF NOT EXISTS idx_notification_deliveries_tenant_id ON notification_deliveries(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_notification_deliveries_channel ON notification_deliveries(channel);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS notification_deliveries;
            """
        )
    )


