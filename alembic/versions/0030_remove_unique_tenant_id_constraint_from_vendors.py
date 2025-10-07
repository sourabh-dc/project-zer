"""remove_unique_tenant_id_constraint_from_vendors

Revision ID: 0030_remove_unique_tenant_id_constraint_from_vendors
Revises: 461ea035e400
Create Date: 2025-10-06 09:44:30.263882+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0030_remove_unique_tenant_id_constraint_from_vendors'
down_revision = '0022_add_scenario_id_to_tenants_new'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """Remove unique constraint on tenant_id from vendors table to allow multiple vendors per tenant"""
    # Drop the unique constraint on tenant_id
    op.execute(sa.text("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS vendors_tenant_id_key;"))


def downgrade() -> None:
    """Add back the unique constraint on tenant_id (one vendor per tenant)"""
    # Add back the unique constraint on tenant_id
    op.execute(sa.text("ALTER TABLE vendors ADD CONSTRAINT vendors_tenant_id_key UNIQUE (tenant_id);"))


