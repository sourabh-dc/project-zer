"""add_scenario_id_to_tenants_new

Revision ID: 461ea035e400
Revises: 3601a86a8f37
Create Date: 2025-10-01 05:21:04.274640+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '461ea035e400'
down_revision = '3601a86a8f37'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add scenario_id column to tenants_new table
    op.execute("""
    ALTER TABLE tenants_new ADD COLUMN scenario_id UUID NULL REFERENCES scenarios(id) ON DELETE SET NULL;
    """)


def downgrade() -> None:
    # Remove scenario_id column from tenants_new table
    op.execute("""
    ALTER TABLE tenants_new DROP COLUMN IF EXISTS scenario_id;
    """)


