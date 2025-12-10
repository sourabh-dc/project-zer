-- Migration script for new features implementation
-- Run this script to update the database schema

BEGIN;

-- Phase 1: Authentication - Add account security fields to users table
ALTER TABLE users
ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS account_locked_until TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE;

-- Create index for faster login lookups
CREATE INDEX IF NOT EXISTS ix_users_email_lower ON users(LOWER(email));

-- Phase 2: Vendor user accounts - Add user_id to vendors table
ALTER TABLE vendors
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(user_id) ON DELETE SET NULL;

-- Create index for faster vendor-user lookups
CREATE INDEX IF NOT EXISTS ix_vendors_user_id ON vendors(user_id);

-- Phase 3: Approval enhancements - Add amount modification fields
ALTER TABLE approval_requests
ADD COLUMN IF NOT EXISTS approved_amount_minor INTEGER,
ADD COLUMN IF NOT EXISTS amount_modification_history JSONB;

-- No schema changes needed for closure (uses existing status field with "closed" value)

COMMIT;

