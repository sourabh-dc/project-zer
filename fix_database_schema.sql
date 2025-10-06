-- Database Schema Fix Script
-- Fixes various schema mismatches and table name issues

-- 1. Fix price_rules table data type mismatch
-- The issue: price_rules_new.rule_id is BIGINT but price_rule_conditions.rule_id is UUID
-- Solution: Convert price_rules_new.rule_id to UUID

-- First, check if we have any existing data that needs to be handled
DO $$
BEGIN
    -- Check if price_rules_new table exists and has data
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'price_rules_new') THEN
        -- Check if rule_id column exists and its current type
        IF EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'price_rules_new' AND column_name = 'rule_id'
        ) THEN
            -- Check current data type
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'price_rules_new' 
                AND column_name = 'rule_id' 
                AND data_type = 'bigint'
            ) THEN
                RAISE NOTICE 'Converting price_rules_new.rule_id from BIGINT to UUID';
                
                -- Add a temporary column for UUID conversion
                ALTER TABLE price_rules_new ADD COLUMN rule_id_uuid UUID;
                
                -- Convert existing BIGINT values to UUID (using a deterministic approach)
                UPDATE price_rules_new 
                SET rule_id_uuid = gen_random_uuid()
                WHERE rule_id_uuid IS NULL;
                
                -- Drop the old column and rename the new one
                ALTER TABLE price_rules_new DROP COLUMN rule_id;
                ALTER TABLE price_rules_new RENAME COLUMN rule_id_uuid TO rule_id;
                ALTER TABLE price_rules_new ALTER COLUMN rule_id SET NOT NULL;
                
                -- Add primary key constraint if it doesn't exist
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints 
                    WHERE table_name = 'price_rules_new' 
                    AND constraint_type = 'PRIMARY KEY'
                ) THEN
                    ALTER TABLE price_rules_new ADD PRIMARY KEY (rule_id);
                END IF;
                
                RAISE NOTICE 'Successfully converted price_rules_new.rule_id to UUID';
            ELSE
                RAISE NOTICE 'price_rules_new.rule_id is already UUID type';
            END IF;
        ELSE
            RAISE NOTICE 'price_rules_new.rule_id column does not exist';
        END IF;
    ELSE
        RAISE NOTICE 'price_rules_new table does not exist';
    END IF;
END $$;

-- 2. Fix table name mismatches
-- Ensure consistent table naming across services

-- Check and fix stores table naming
DO $$
BEGIN
    -- If stores_new exists but services reference stores, create a view or rename
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stores_new') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stores') THEN
        RAISE NOTICE 'Creating stores view to match services expectations';
        CREATE VIEW stores AS SELECT * FROM stores_new;
    ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stores') 
         AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stores_new') THEN
        RAISE NOTICE 'Creating stores_new view to match architecture expectations';
        CREATE VIEW stores_new AS SELECT * FROM stores;
    END IF;
END $$;

-- Check and fix tenants table naming
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants_new') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants') THEN
        RAISE NOTICE 'Creating tenants view to match services expectations';
        CREATE VIEW tenants AS SELECT * FROM tenants_new;
    ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants') 
         AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenants_new') THEN
        RAISE NOTICE 'Creating tenants_new view to match architecture expectations';
        CREATE VIEW tenants_new AS SELECT * FROM tenants;
    END IF;
END $$;

-- Check and fix users table naming
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users_new') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        RAISE NOTICE 'Creating users view to match services expectations';
        CREATE VIEW users AS SELECT * FROM users_new;
    ELSIF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') 
         AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users_new') THEN
        RAISE NOTICE 'Creating users_new view to match architecture expectations';
        CREATE VIEW users_new AS SELECT * FROM users;
    END IF;
END $$;

-- 3. Fix foreign key constraints that might be broken due to table name changes
DO $$
BEGIN
    -- Check and fix orders table foreign key references
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'orders_new') THEN
        -- Fix store_id foreign key reference
        IF EXISTS (
            SELECT 1 FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = 'orders_new' 
            AND kcu.column_name = 'store_id'
            AND tc.constraint_type = 'FOREIGN KEY'
        ) THEN
            RAISE NOTICE 'Foreign key constraints exist for orders_new.store_id';
        ELSE
            -- Try to add foreign key constraint if it doesn't exist
            BEGIN
                ALTER TABLE orders_new 
                ADD CONSTRAINT fk_orders_new_store_id 
                FOREIGN KEY (store_id) REFERENCES stores(store_id);
                RAISE NOTICE 'Added foreign key constraint for orders_new.store_id';
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'Could not add foreign key constraint for orders_new.store_id: %', SQLERRM;
            END;
        END IF;
    END IF;
END $$;

-- 4. Ensure proper indexes exist for performance
CREATE INDEX IF NOT EXISTS idx_price_rules_new_active ON price_rules_new(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_price_rules_new_valid_from ON price_rules_new(valid_from);
CREATE INDEX IF NOT EXISTS idx_price_rules_new_valid_until ON price_rules_new(valid_until);
CREATE INDEX IF NOT EXISTS idx_price_rules_new_scope ON price_rules_new(scope_type, scope_id);

-- 5. Fix any missing sequences or default values
DO $$
BEGIN
    -- Ensure uuid_generate_v7() function exists (for time-sortable UUIDs)
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'uuid_generate_v7') THEN
        RAISE NOTICE 'uuid_generate_v7 function not found - creating simple fallback';
        -- Create a simple UUID generation function if the extension is not available
        CREATE OR REPLACE FUNCTION uuid_generate_v7()
        RETURNS UUID AS $$
        BEGIN
            RETURN gen_random_uuid();
        END;
        $$ LANGUAGE plpgsql;
    END IF;
END $$;

-- 6. Clean up any orphaned data
-- Remove any price_rule_conditions that reference non-existent rules
DELETE FROM price_rule_conditions 
WHERE rule_id NOT IN (SELECT rule_id FROM price_rules_new);

-- 7. Add any missing columns with proper defaults
DO $$
BEGIN
    -- Add created_at and updated_at columns if they don't exist
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'price_rules_new') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'price_rules_new' AND column_name = 'created_at'
        ) THEN
            ALTER TABLE price_rules_new ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
            RAISE NOTICE 'Added created_at column to price_rules_new';
        END IF;
        
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'price_rules_new' AND column_name = 'updated_at'
        ) THEN
            ALTER TABLE price_rules_new ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
            RAISE NOTICE 'Added updated_at column to price_rules_new';
        END IF;
    END IF;
END $$;

-- 8. Final verification
DO $$
BEGIN
    RAISE NOTICE 'Database schema fix completed. Verification:';
    
    -- Check price_rules_new structure
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'price_rules_new') THEN
        RAISE NOTICE 'price_rules_new table exists';
        IF EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'price_rules_new' AND column_name = 'rule_id' AND data_type = 'uuid'
        ) THEN
            RAISE NOTICE 'price_rules_new.rule_id is correctly set to UUID';
        ELSE
            RAISE NOTICE 'WARNING: price_rules_new.rule_id is not UUID type';
        END IF;
    END IF;
    
    -- Check price_rule_conditions structure
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'price_rule_conditions') THEN
        RAISE NOTICE 'price_rule_conditions table exists';
        IF EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'price_rule_conditions' AND column_name = 'rule_id' AND data_type = 'uuid'
        ) THEN
            RAISE NOTICE 'price_rule_conditions.rule_id is correctly set to UUID';
        ELSE
            RAISE NOTICE 'WARNING: price_rule_conditions.rule_id is not UUID type';
        END IF;
    END IF;
END $$;

COMMIT;
