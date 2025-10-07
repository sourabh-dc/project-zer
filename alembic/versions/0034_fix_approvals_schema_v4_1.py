"""fix_approvals_schema_v4_1

Revision ID: 0034_fix_approvals_schema_v4_1
Revises: 0033_fix_billing_schema_v4_1
Create Date: 2025-10-07 11:22:08.246378+00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '0034_fix_approvals_schema_v4_1'
down_revision = '0033_fix_billing_schema_v4_1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Fix Approvals Service Schema for Production Features - Add missing columns and tables"""
    
    # Add missing columns to approval_requests_new
    op.add_column('approval_requests_new', sa.Column('tenant_id', sa.UUID(), nullable=True))
    op.add_column('approval_requests_new', sa.Column('current_step_number', sa.Integer(), nullable=True, server_default='1'))
    
    # Create approval_request_approvers table
    op.create_table('approval_request_approvers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('request_id', sa.UUID(), nullable=False),
        sa.Column('approver_user_id', sa.UUID(), nullable=False),
        sa.Column('approver_role', sa.String(length=100), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('escalation_sent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'approved', 'denied', 'skipped')", name='approval_request_approvers_status_check'),
        sa.ForeignKeyConstraint(['request_id'], ['approval_requests_new.request_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Add indexes for performance
    op.create_index('idx_approval_request_approvers_request_id', 'approval_request_approvers', ['request_id'])
    op.create_index('idx_approval_request_approvers_user_id', 'approval_request_approvers', ['approver_user_id'])
    op.create_index('idx_approval_request_approvers_step', 'approval_request_approvers', ['request_id', 'step_number'])
    op.create_index('idx_approval_requests_tenant_id', 'approval_requests_new', ['tenant_id'])
    
    # Enable RLS on new table
    op.execute(text("ALTER TABLE approval_request_approvers ENABLE ROW LEVEL SECURITY"))
    
    # Create RLS policy for approval_request_approvers
    op.execute(text("""
        CREATE POLICY approval_request_approvers_tenant_isolation ON approval_request_approvers
        FOR ALL
        TO PUBLIC
        USING (EXISTS (
            SELECT 1 FROM approval_requests_new ar 
            WHERE ar.request_id = approval_request_approvers.request_id 
            AND ar.tenant_id = current_setting('app.current_tenant_id')::UUID
        ))
    """))
    
    # Update existing approval_requests_new records with a default tenant_id
    op.execute(text("UPDATE approval_requests_new SET tenant_id = '550e8400-e29b-41d4-a716-446655440000'::UUID WHERE tenant_id IS NULL"))
    
    # Make tenant_id NOT NULL after setting defaults
    op.alter_column('approval_requests_new', 'tenant_id', nullable=False)
    
    # Create RLS policy for approval_requests_new tenant isolation
    op.execute(text("""
        CREATE POLICY approval_requests_tenant_isolation ON approval_requests_new
        FOR ALL
        TO PUBLIC
        USING (tenant_id = current_setting('app.current_tenant_id')::UUID)
    """))
    
    # Add trigger for updated_at
    op.execute(text("""
        CREATE OR REPLACE FUNCTION update_approval_request_approvers_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))
    
    op.execute(text("""
        CREATE TRIGGER trigger_approval_request_approvers_updated_at
            BEFORE UPDATE ON approval_request_approvers
            FOR EACH ROW
            EXECUTE FUNCTION update_approval_request_approvers_updated_at();
    """))


def downgrade() -> None:
    """Revert approvals schema changes"""
    
    # Drop trigger and function
    op.execute(text("DROP TRIGGER IF EXISTS trigger_approval_request_approvers_updated_at ON approval_request_approvers"))
    op.execute(text("DROP FUNCTION IF EXISTS update_approval_request_approvers_updated_at()"))
    
    # Drop RLS policies
    op.execute(text("DROP POLICY IF EXISTS approval_request_approvers_tenant_isolation ON approval_request_approvers"))
    op.execute(text("DROP POLICY IF EXISTS approval_requests_tenant_isolation ON approval_requests_new"))
    
    # Drop indexes
    op.drop_index('idx_approval_request_approvers_request_id', 'approval_request_approvers')
    op.drop_index('idx_approval_request_approvers_user_id', 'approval_request_approvers')
    op.drop_index('idx_approval_request_approvers_step', 'approval_request_approvers')
    op.drop_index('idx_approval_requests_tenant_id', 'approval_requests_new')
    
    # Drop table
    op.drop_table('approval_request_approvers')
    
    # Drop columns
    op.drop_column('approval_requests_new', 'current_step_number')
    op.drop_column('approval_requests_new', 'tenant_id')