"""add_tenant_links_table

Revision ID: 721371ee26d5
Revises: cad2337db715
Create Date: 2025-09-28 10:22:58.758424+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '721371ee26d5'
down_revision = 'cad2337db715'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS tenant_links (
              id                 BIGSERIAL PRIMARY KEY,
              parent_tenant_id   VARCHAR(100) NOT NULL,
              child_tenant_id    VARCHAR(100) NOT NULL,
              relationship       VARCHAR(30) NOT NULL DEFAULT 'distributor',
              created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at         TIMESTAMPTZ NULL,
              UNIQUE (parent_tenant_id, child_tenant_id, relationship)
            );

            -- Create indexes for better performance
            CREATE INDEX IF NOT EXISTS idx_tenant_links_parent_tenant_id ON tenant_links(parent_tenant_id);
            CREATE INDEX IF NOT EXISTS idx_tenant_links_child_tenant_id ON tenant_links(child_tenant_id);
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DROP TABLE IF EXISTS tenant_links;
            """
        )
    )


