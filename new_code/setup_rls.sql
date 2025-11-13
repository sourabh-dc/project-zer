-- PostgreSQL Row Level Security (RLS) Setup Script
-- Run this script after the tables are created to enable tenant isolation

-- Enable RLS on tenant-scoped tables
ALTER TABLE sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_centres ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for Sites
CREATE POLICY site_tenant_isolation ON sites
    USING (tenant_id::text = current_setting('app.current_tenant', true));

-- Create RLS policies for Stores
CREATE POLICY store_tenant_isolation ON stores
    USING (tenant_id::text = current_setting('app.current_tenant', true));

-- Create RLS policies for Users
CREATE POLICY user_tenant_isolation ON users
    USING (tenant_id::text = current_setting('app.current_tenant', true));

-- Create RLS policies for Vendors
CREATE POLICY vendor_tenant_isolation ON vendors
    USING (tenant_id::text = current_setting('app.current_tenant', true));

-- Create RLS policies for Cost Centres
CREATE POLICY cost_centre_tenant_isolation ON cost_centres
    USING (tenant_id::text = current_setting('app.current_tenant', true));

-- Note: Tenants table does NOT have RLS enabled as it's the root entity
-- Note: Roles table does NOT have RLS as roles are global across all tenants

-- Grant necessary permissions (adjust username as needed)
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO zeroque;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO zeroque;

-- Verify RLS is enabled
SELECT schemaname, tablename, rowsecurity 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename IN ('sites', 'stores', 'users', 'vendors', 'cost_centres');

-- View policies
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname = 'public';


