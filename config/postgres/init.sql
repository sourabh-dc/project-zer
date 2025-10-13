-- ZeroQue Production Database Initialization
-- Enhanced security, performance, and monitoring

-- Create production database
CREATE DATABASE zeroque_prod;

-- Connect to the production database
\c zeroque_prod;

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Create production user with limited privileges
CREATE USER zeroque_app WITH PASSWORD 'zeroque_app_2024_secure';
CREATE USER zeroque_readonly WITH PASSWORD 'zeroque_readonly_2024_secure';

-- Grant basic privileges
GRANT CONNECT ON DATABASE zeroque_prod TO zeroque_app;
GRANT CONNECT ON DATABASE zeroque_prod TO zeroque_readonly;

-- Create schemas
CREATE SCHEMA IF NOT EXISTS zeroque;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS metrics;

-- Set default schema
ALTER DATABASE zeroque_prod SET search_path TO zeroque, public;

-- Production RLS Policies Template
-- These will be applied to all tenant-specific tables

-- Function to get current tenant_id from JWT
CREATE OR REPLACE FUNCTION zeroque.get_current_tenant_id()
RETURNS UUID AS $$
BEGIN
    -- This will be set by application context
    RETURN COALESCE(current_setting('app.current_tenant_id', true)::UUID, '00000000-0000-0000-0000-000000000000'::UUID);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get current user_id from JWT
CREATE OR REPLACE FUNCTION zeroque.get_current_user_id()
RETURNS UUID AS $$
BEGIN
    -- This will be set by application context
    RETURN COALESCE(current_setting('app.current_user_id', true)::UUID, '00000000-0000-0000-0000-000000000000'::UUID);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Audit logging function
CREATE OR REPLACE FUNCTION audit.log_table_changes()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit.table_changes (
        table_name,
        operation,
        old_values,
        new_values,
        changed_by,
        changed_at,
        tenant_id
    ) VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) ELSE NULL END,
        zeroque.get_current_user_id(),
        NOW(),
        COALESCE(NEW.tenant_id, OLD.tenant_id)
    );
    
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create audit tables
CREATE TABLE IF NOT EXISTS audit.table_changes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    old_values JSONB,
    new_values JSONB,
    changed_by UUID,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    tenant_id UUID,
    INDEX idx_audit_table_name (table_name),
    INDEX idx_audit_tenant_id (tenant_id),
    INDEX idx_audit_changed_at (changed_at)
);

-- Performance monitoring views
CREATE OR REPLACE VIEW metrics.slow_queries AS
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    rows,
    100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0) AS hit_percent
FROM pg_stat_statements
WHERE mean_time > 100  -- Queries taking more than 100ms on average
ORDER BY mean_time DESC;

-- Connection monitoring
CREATE OR REPLACE VIEW metrics.active_connections AS
SELECT 
    datname,
    usename,
    application_name,
    client_addr,
    state,
    query_start,
    state_change,
    query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY query_start;

-- Database size monitoring
CREATE OR REPLACE VIEW metrics.database_sizes AS
SELECT 
    datname,
    pg_size_pretty(pg_database_size(datname)) AS size,
    pg_database_size(datname) AS size_bytes
FROM pg_database
ORDER BY pg_database_size(datname) DESC;

-- Grant permissions
GRANT USAGE ON SCHEMA zeroque TO zeroque_app;
GRANT USAGE ON SCHEMA audit TO zeroque_app;
GRANT USAGE ON SCHEMA metrics TO zeroque_readonly;

GRANT SELECT ON metrics.slow_queries TO zeroque_readonly;
GRANT SELECT ON metrics.active_connections TO zeroque_readonly;
GRANT SELECT ON metrics.database_sizes TO zeroque_readonly;

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_audit_tenant_id ON audit.table_changes (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_table_name ON audit.table_changes (table_name);
CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON audit.table_changes (changed_at);

-- Performance tuning parameters
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 100;
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;

-- Logging configuration
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log queries taking more than 1 second
ALTER SYSTEM SET log_statement = 'mod';
ALTER SYSTEM SET log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h ';

-- Security settings
ALTER SYSTEM SET ssl = on;
ALTER SYSTEM SET password_encryption = scram-sha-256;
ALTER SYSTEM SET row_security = on;

-- Reload configuration
SELECT pg_reload_conf();

-- Create production monitoring user
CREATE USER zeroque_monitor WITH PASSWORD 'zeroque_monitor_2024_secure';
GRANT pg_monitor TO zeroque_monitor;
GRANT SELECT ON metrics.slow_queries TO zeroque_monitor;
GRANT SELECT ON metrics.active_connections TO zeroque_monitor;
GRANT SELECT ON metrics.database_sizes TO zeroque_monitor;

-- Success message
\echo 'ZeroQue Production Database initialized successfully!'
\echo 'Database: zeroque_prod'
\echo 'Schema: zeroque'
\echo 'Users: zeroque_app, zeroque_readonly, zeroque_monitor'
\echo 'Extensions: uuid-ossp, pg_stat_statements, pg_trgm, btree_gin'
\echo 'Audit logging: enabled'
\echo 'Performance monitoring: enabled'


