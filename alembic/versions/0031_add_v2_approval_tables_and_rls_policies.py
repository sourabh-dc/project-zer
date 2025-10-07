"""Add V2 approval tables and RLS policies

Revision ID: 0031_add_v2_approval_tables_and_rls_policies
Revises: 0030_remove_unique_tenant_id_constraint_from_vendors
Create Date: 2025-10-07 05:31:18.955732+00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0031_add_v2_approval_tables_and_rls_policies'
down_revision = '0030_remove_unique_tenant_id_constraint_from_vendors'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create approval_chains table
    op.create_table('approval_chains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cost_centre_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('is_sequential', sa.Boolean(), nullable=False, default=True),
        sa.Column('priority', sa.Integer(), nullable=False, default=1),
        sa.Column('active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cost_centre_id', 'name', name='uq_approval_chain_cc_name')
    )
    op.create_index('ix_approval_chains_cost_centre_id', 'approval_chains', ['cost_centre_id'])
    op.create_index('ix_approval_chains_active', 'approval_chains', ['active'])

    # Create approval_chain_steps table
    op.create_table('approval_chain_steps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('approver_role_id', sa.String(length=100), nullable=True),
        sa.Column('approver_user_id', sa.String(length=100), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('required_approvals', sa.Integer(), nullable=False, default=1),
        sa.Column('timeout_hours', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['chain_id'], ['approval_chains.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('approver_role_id IS NOT NULL OR approver_user_id IS NOT NULL', name='ck_approval_step_has_approver')
    )
    op.create_index('ix_approval_chain_steps_chain_id', 'approval_chain_steps', ['chain_id'])
    op.create_index('ix_approval_chain_steps_order', 'approval_chain_steps', ['order'])

    # Create approval_requests_new table
    op.create_table('approval_requests_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=100), nullable=False),
        sa.Column('cost_centre_id', sa.String(length=100), nullable=False),
        sa.Column('requester_user_id', sa.String(length=100), nullable=False),
        sa.Column('user_scope_id', sa.String(length=100), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False, default='GBP'),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('remaining_minor', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'denied', 'expired', 'cancelled')", name='ck_approval_request_status')
    )
    op.create_index('ix_approval_requests_new_tenant_id', 'approval_requests_new', ['tenant_id'])
    op.create_index('ix_approval_requests_new_cost_centre_id', 'approval_requests_new', ['cost_centre_id'])
    op.create_index('ix_approval_requests_new_status', 'approval_requests_new', ['status'])
    op.create_index('ix_approval_requests_new_requester_user_id', 'approval_requests_new', ['requester_user_id'])

    # Create approval_request_approvers table
    op.create_table('approval_request_approvers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('approver_user_id', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['approval_requests_new.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_id', 'approver_user_id', name='uq_approval_request_approver'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'denied')", name='ck_approval_approver_status')
    )
    op.create_index('ix_approval_request_approvers_request_id', 'approval_request_approvers', ['request_id'])
    op.create_index('ix_approval_request_approvers_approver_user_id', 'approval_request_approvers', ['approver_user_id'])
    op.create_index('ix_approval_request_approvers_status', 'approval_request_approvers', ['status'])

    # Add RLS policies
    op.execute("ALTER TABLE approval_chains ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approval_chain_steps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approval_requests_new ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approval_request_approvers ENABLE ROW LEVEL SECURITY")

    # Create RLS policies for tenant isolation
    op.execute("""
        CREATE POLICY approval_chains_tenant_isolation ON approval_chains
        FOR ALL TO PUBLIC
        USING (cost_centre_id IN (
            SELECT cost_centre_id FROM cost_centres_new 
            WHERE tenant_id = current_setting('app.current_tenant_id', true)
        ))
    """)

    op.execute("""
        CREATE POLICY approval_chain_steps_tenant_isolation ON approval_chain_steps
        FOR ALL TO PUBLIC
        USING (chain_id IN (
            SELECT ac.id FROM approval_chains ac
            JOIN cost_centres_new cc ON ac.cost_centre_id = cc.cost_centre_id
            WHERE cc.tenant_id = current_setting('app.current_tenant_id', true)
        ))
    """)

    op.execute("""
        CREATE POLICY approval_requests_tenant_isolation ON approval_requests_new
        FOR ALL TO PUBLIC
        USING (tenant_id = current_setting('app.current_tenant_id', true))
    """)

    op.execute("""
        CREATE POLICY approval_request_approvers_tenant_isolation ON approval_request_approvers
        FOR ALL TO PUBLIC
        USING (request_id IN (
            SELECT id FROM approval_requests_new 
            WHERE tenant_id = current_setting('app.current_tenant_id', true)
        ))
    """)


def downgrade() -> None:
    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS approval_request_approvers_tenant_isolation ON approval_request_approvers")
    op.execute("DROP POLICY IF EXISTS approval_requests_tenant_isolation ON approval_requests_new")
    op.execute("DROP POLICY IF EXISTS approval_chain_steps_tenant_isolation ON approval_chain_steps")
    op.execute("DROP POLICY IF EXISTS approval_chains_tenant_isolation ON approval_chains")

    # Drop tables in reverse order
    op.drop_table('approval_request_approvers')
    op.drop_table('approval_requests_new')
    op.drop_table('approval_chain_steps')
    op.drop_table('approval_chains')


