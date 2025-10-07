-- Migration script to move from site-level to tenant-level subscriptions
-- This script creates the new tenant_subscriptions table and migrates data

-- 1. Create tenant_subscriptions table
CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) UNIQUE NOT NULL,
    plan_code VARCHAR(50) NOT NULL REFERENCES subscription_plans(code),
    payment_method VARCHAR(20) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    external_id VARCHAR(100) NOT NULL,
    current_period_start TIMESTAMP WITH TIME ZONE,
    current_period_end TIMESTAMP WITH TIME ZONE,
    trial_end TIMESTAMP WITH TIME ZONE,
    canceled_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- 2. Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant_id ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_external_id ON tenant_subscriptions(external_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_plan_code ON tenant_subscriptions(plan_code);

-- 3. Migrate data from site_subscriptions to tenant_subscriptions
-- For each tenant, take the most recent subscription (by created_at)
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

-- 4. Update subscription_usage table to remove site_id
-- First, let's check if the table has site_id column
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'subscription_usage' AND column_name = 'site_id'
    ) THEN
        -- Remove site_id from subscription_usage
        ALTER TABLE subscription_usage DROP COLUMN IF EXISTS site_id;
    END IF;
END $$;

-- 5. Update usage_aggregates_daily table to remove site_id and store_id
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

-- 6. Create RLS policy for tenant_subscriptions
CREATE POLICY IF NOT EXISTS tenant_isolation_tenant_subscriptions
    ON tenant_subscriptions
    FOR ALL
    TO zeroque_app
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- 7. Enable RLS on tenant_subscriptions
ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY;

-- 8. Verify migration
SELECT 
    'tenant_subscriptions' as table_name,
    COUNT(*) as record_count
FROM tenant_subscriptions
UNION ALL
SELECT 
    'site_subscriptions' as table_name,
    COUNT(*) as record_count
FROM site_subscriptions;

-- 9. Show sample migrated data
SELECT 
    tenant_id,
    plan_code,
    status,
    created_at
FROM tenant_subscriptions
ORDER BY created_at DESC
LIMIT 5;

-- 10. Optional: Drop site_subscriptions table after verification
-- Uncomment the following line only after confirming migration is successful
-- DROP TABLE IF EXISTS site_subscriptions CASCADE;
