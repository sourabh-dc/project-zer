"""add_notifications_table

Revision ID: cad2337db715
Revises: a5bfe3447d51
Create Date: 2025-09-28 10:17:39.045238+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cad2337db715'
down_revision = 'a5bfe3447d51'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS notifications (
              id               BIGSERIAL PRIMARY KEY,
              tenant_id        VARCHAR(100) NOT NULL,
              target_user_id   VARCHAR(100) NULL,
              channel          VARCHAR(20) NOT NULL DEFAULT 'dev',
              subject          VARCHAR(200) NOT NULL,
              body             TEXT NOT NULL,
              created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at       TIMESTAMPTZ NULL
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_notifications_tenant_id ON notifications(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_target_user_id ON notifications(target_user_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);
            CREATE INDEX IF NOT EXISTS idx_notifications_channel ON notifications(channel);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS notifications;
            """
        )
    )


