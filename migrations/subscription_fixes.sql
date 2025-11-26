-- Migration: Fix subscription and entitlement issues
-- Date: 2025-01-27
-- Description: Add missing columns and indexes for proper subscription management

-- ============================================================================
-- TenantSubscription Updates
-- ============================================================================

-- Add pending_plan_code for upgrade/downgrade support
ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS pending_plan_code VARCHAR(50);

-- Rename trial_end to trial_ends_at for consistency (if it exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tenant_subscriptions' AND column_name = 'trial_end') THEN
        ALTER TABLE tenant_subscriptions RENAME COLUMN trial_end TO trial_ends_at;
    END IF;
END
$$;

-- Add trial_ends_at if it doesn't exist
ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP WITH TIME ZONE;

-- Add ends_at for tracking when subscription actually ends (after cancellation)
ALTER TABLE tenant_subscriptions ADD COLUMN IF NOT EXISTS ends_at TIMESTAMP WITH TIME ZONE;

-- Update status column default and constraints
ALTER TABLE tenant_subscriptions ALTER COLUMN status SET DEFAULT 'trialing';

-- Add index on tenant_id for faster lookups
CREATE INDEX IF NOT EXISTS ix_tenant_subscription_tenant_id ON tenant_subscriptions(tenant_id);

-- ============================================================================
-- SubscriptionUsage Updates
-- ============================================================================

-- Add composite index for efficient usage lookups
CREATE INDEX IF NOT EXISTS ix_subscription_usage_composite 
ON subscription_usage(tenant_id, feature_code, period_start);

-- ============================================================================
-- Data Migration: Update existing subscriptions
-- ============================================================================

-- Set default status for any NULL statuses
UPDATE tenant_subscriptions SET status = 'active' WHERE status IS NULL;

-- Ensure current_period_start and current_period_end are set for existing records
UPDATE tenant_subscriptions 
SET current_period_start = created_at,
    current_period_end = created_at + INTERVAL '1 year'
WHERE current_period_start IS NULL;

COMMENT ON COLUMN tenant_subscriptions.status IS 'trialing, active, canceled, unpaid, past_due';
COMMENT ON COLUMN tenant_subscriptions.pending_plan_code IS 'Plan to switch to at end of current period (for upgrades/downgrades)';
COMMENT ON COLUMN tenant_subscriptions.trial_ends_at IS 'When the trial period ends';
COMMENT ON COLUMN tenant_subscriptions.ends_at IS 'When subscription access ends (after cancellation grace period)';

