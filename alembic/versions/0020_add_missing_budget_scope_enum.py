"""add_missing_budget_scope_enum

Revision ID: 62f0c0cc1f1f
Revises: 3e3cb325a0ea
Create Date: 2025-09-30 15:18:24.400117+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '62f0c0cc1f1f'
down_revision = '3e3cb325a0ea'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create budget_scope enum
    op.execute("CREATE TYPE budget_scope AS ENUM ('TENANT', 'SITE', 'STORE', 'USER', 'COST_CENTRE', 'VENDOR');")


def downgrade() -> None:
    # Drop budget_scope enum
    op.execute("DROP TYPE budget_scope;")


