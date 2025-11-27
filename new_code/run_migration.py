#!/usr/bin/env python3
"""Run database migration for new features"""
import os
import sys
from sqlalchemy import text
from core.db_config import SessionLocal, engine

def run_migration():
    """Run migration SQL"""
    migration_sql = """
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
    """
    
    db = SessionLocal()
    try:
        print("🔄 Running database migration...")
        for statement in migration_sql.strip().split(';'):
            statement = statement.strip()
            if statement:
                db.execute(text(statement))
        db.commit()
        print("✅ Migration completed successfully!")
        return True
    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)

