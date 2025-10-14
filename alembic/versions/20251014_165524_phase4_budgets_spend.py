"""Phase 4: Budgets & Spend

Revision ID: phase4_budgets_spend
Revises: phase3_catalogue_inventory
Create Date: 2025-01-14 06:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg

# revision identifiers, used by Alembic.
revision = 'phase4_budgets_spend'
down_revision = 'phase3_catalogue_inventory'
branch_labels = None
depends_on = None


def upgrade():
    # Create cost_centres table
    try:
        op.create_table('cost_centres',
            sa.Column('cost_centre_id', pg.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('name', sa.String(200), nullable=False),
            sa.Column('code', sa.String(50), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('parent_cost_centre_id', sa.UUID(), nullable=True),
            sa.Column('budget_owner_id', sa.UUID(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['parent_cost_centre_id'], ['cost_centres.cost_centre_id'], ),
            sa.PrimaryKeyConstraint('cost_centre_id')
        )
    except:
        pass

    # Create budgets table
    try:
        op.create_table('budgets',
            sa.Column('budget_id', sa.UUID(), nullable=False),
            sa.Column('cost_centre_id', sa.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('budget_year', sa.Integer(), nullable=False),
            sa.Column('budget_month', sa.Integer(), nullable=False),
            sa.Column('budget_type', sa.String(50), nullable=False),
            sa.Column('budget_amount_minor', sa.BigInteger(), nullable=False),
            sa.Column('spent_amount_minor', sa.BigInteger(), nullable=False),
            sa.Column('available_amount_minor', sa.BigInteger(), nullable=False),
            sa.Column('currency', sa.String(3), nullable=False),
            sa.Column('status', sa.String(20), nullable=False),
            sa.Column('approval_workflow_id', sa.UUID(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['cost_centre_id'], ['cost_centres.cost_centre_id'], ),
            sa.PrimaryKeyConstraint('budget_id')
        )
    except:
        # Table might already exist
        pass

    # Create budget_transactions table
    try:
        op.create_table('budget_transactions',
            sa.Column('transaction_id', sa.UUID(), nullable=False),
            sa.Column('budget_id', sa.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('amount_minor', sa.BigInteger(), nullable=False),
            sa.Column('transaction_type', sa.String(50), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('reference_id', sa.String(100), nullable=True),
            sa.Column('reference_type', sa.String(50), nullable=True),
            sa.Column('approval_id', sa.UUID(), nullable=True),
            sa.Column('is_approved', sa.Boolean(), nullable=False),
            sa.Column('created_by', sa.UUID(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['budget_id'], ['budgets.budget_id'], ),
            sa.PrimaryKeyConstraint('transaction_id')
        )
    except:
        # Table might already exist
        pass

    # Create budget_alerts table
    try:
        op.create_table('budget_alerts',
            sa.Column('alert_id', sa.UUID(), nullable=False),
            sa.Column('budget_id', sa.UUID(), nullable=False),
            sa.Column('tenant_id', sa.UUID(), nullable=False),
            sa.Column('alert_type', sa.String(50), nullable=False),
            sa.Column('threshold_percentage', sa.Numeric(5, 2), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('is_acknowledged', sa.Boolean(), nullable=False),
            sa.Column('acknowledged_by', sa.UUID(), nullable=True),
            sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['budget_id'], ['budgets.budget_id'], ),
            sa.PrimaryKeyConstraint('alert_id')
        )
    except:
        # Table might already exist
        pass

    # Create indexes for performance
    try:
        op.create_index(op.f('ix_cost_centres_tenant_id'), 'cost_centres', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_cost_centres_code'), 'cost_centres', ['code'], unique=False)
        op.create_index(op.f('ix_budgets_cost_centre_id'), 'budgets', ['cost_centre_id'], unique=False)
        op.create_index(op.f('ix_budgets_tenant_id'), 'budgets', ['tenant_id'], unique=False)
        op.create_index(op.f('ix_budget_transactions_budget_id'), 'budget_transactions', ['budget_id'], unique=False)
        op.create_index(op.f('ix_budget_alerts_budget_id'), 'budget_alerts', ['budget_id'], unique=False)
    except:
        # Indexes might already exist
        pass


def downgrade():
    # Remove indexes
    try:
        op.drop_index(op.f('ix_budget_alerts_budget_id'), table_name='budget_alerts')
        op.drop_index(op.f('ix_budget_transactions_budget_id'), table_name='budget_transactions')
        op.drop_index(op.f('ix_budgets_tenant_id'), table_name='budgets')
        op.drop_index(op.f('ix_budgets_cost_centre_id'), table_name='budgets')
        op.drop_index(op.f('ix_cost_centres_code'), table_name='cost_centres')
        op.drop_index(op.f('ix_cost_centres_tenant_id'), table_name='cost_centres')
    except:
        pass

    # Drop tables
    try:
        op.drop_table('budget_alerts')
        op.drop_table('budget_transactions')
        op.drop_table('budgets')
        op.drop_table('cost_centres')
    except:
        pass
