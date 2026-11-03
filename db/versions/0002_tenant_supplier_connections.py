"""tenant_supplier_connections — buyer↔supplier marketplace association

Revision ID: 0002_tenant_supplier_connections
Revises: 0001_baseline
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0002_tenant_supplier_connections"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_supplier_connections",
        sa.Column("connection_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "buyer_tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="connected"),
        sa.Column(
            "connected_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ux_tenant_supplier_pair",
        "tenant_supplier_connections",
        ["buyer_tenant_id", "supplier_tenant_id"],
        unique=True,
    )
    op.create_index(
        "ix_tenant_supplier_connections_buyer_tenant_id",
        "tenant_supplier_connections",
        ["buyer_tenant_id"],
    )
    op.create_index(
        "ix_tenant_supplier_connections_supplier_tenant_id",
        "tenant_supplier_connections",
        ["supplier_tenant_id"],
    )
    op.create_index(
        "ix_tenant_supplier_connections_status",
        "tenant_supplier_connections",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("tenant_supplier_connections")
