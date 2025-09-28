"""baseline empty revision

Revision ID: 0001_baseline
Revises: 
Create Date: 2025-09-25 00:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Baseline marker; use future revisions to capture changes
    pass


def downgrade() -> None:
    pass


