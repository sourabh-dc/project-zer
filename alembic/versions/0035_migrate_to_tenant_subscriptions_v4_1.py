"""migrate_to_tenant_subscriptions_v4_1

Revision ID: 0035_migrate_to_tenant_subscriptions_v4_1
Revises: 0034_fix_approvals_schema_v4_1
Create Date: 2025-10-07 11:23:45.807245+00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '0035_migrate_to_tenant_subscriptions_v4_1'
down_revision = '0034_fix_approvals_schema_v4_1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migration script to move from site-level to tenant-level subscriptions"""
    
    # Create tenant_subscriptions table
    op.create_table('tenant_subscriptions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('tenant_id', sa.String(length=100), nullable=False),
        sa.Column('plan_code', sa.String(length=50), nullable=False),
        sa.Column('payment_method', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='active'),
        sa.Column('external_id', sa.String(length=100), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['plan_code'], ['subscription_plans.code'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id')
    )
    
    # Create indexes for performance
    op.create_index('idx_tenant_subscriptions_tenant_id', 'tenant_subscriptions', ['tenant_id'])
    op.create_index('idx_tenant_subscriptions_external_id', 'tenant_subscriptions', ['external_id'])
    op.create_index('idx_tenant_subscriptions_plan_code', 'tenant_subscriptions', ['plan_code'])
    
    # Migrate data from site_subscriptions to tenant_subscriptions
    op.execute(text("""
        INSERT INTO tenant_subscriptions (
            tenant_id, plan_code, payment_method, status, external_id,
            current_period_start, current_period_end, trial_end, canceled_at,
            created_at, updated_at
        )
        SELECT DISTINCT ON (tenant_id)
            tenant_id,
            plan_code,
            payment_method,
            status,
            external_id,
            current_period_start,
            current_period_end,
            trial_end,
            canceled_at,
            created_at,
            updated_at
        FROM site_subscriptions
        WHERE status IN ('active', 'trialing')
        ORDER BY tenant_id, created_at DESC
        ON CONFLICT (tenant_id) DO NOTHING;
    """))
    
    # Update subscription_usage table to remove site_id
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'subscription_usage' AND column_name = 'site_id'
            ) THEN
                ALTER TABLE subscription_usage DROP COLUMN IF EXISTS site_id;
            END IF;
        END $$;
    """))
    
    # Update usage_aggregates_daily table to remove site_id and store_id
    op.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'usage_aggregates_daily' AND column_name = 'site_id'
            ) THEN
                ALTER TABLE usage_aggregates_daily DROP COLUMN IF EXISTS site_id;
            END IF;
            
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'usage_aggregates_daily' AND column_name = 'store_id'
            ) THEN
                ALTER TABLE usage_aggregates_daily DROP COLUMN IF EXISTS store_id;
            END IF;
        END $$;
    """))
    
    # Create RLS policy for tenant_subscriptions
    op.execute(text("""
        CREATE POLICY IF NOT EXISTS tenant_isolation_tenant_subscriptions
        ON tenant_subscriptions
        FOR ALL
        TO zeroque_app
        USING (tenant_id = current_setting('app.current_tenant_id', true));
    """))
    
    # Enable RLS on tenant_subscriptions
    op.execute(text("ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    """Revert tenant subscription migration"""
    
    # Drop RLS policy
    op.execute(text("DROP POLICY IF EXISTS tenant_isolation_tenant_subscriptions ON tenant_subscriptions"))
    
    # Drop indexes
    op.drop_index('idx_tenant_subscriptions_tenant_id', 'tenant_subscriptions')
    op.drop_index('idx_tenant_subscriptions_external_id', 'tenant_subscriptions')
    op.drop_index('idx_tenant_subscriptions_plan_code', 'tenant_subscriptions')
    
    # Drop table
    op.drop_table('tenant_subscriptions')