from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
-- Recreate stripe_charges table with proper column types
DO $$
BEGIN
    -- First, drop the unique constraint if it exists
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'stripe_charges_payment_intent_id_key') THEN
        ALTER TABLE stripe_charges DROP CONSTRAINT IF EXISTS stripe_charges_payment_intent_id_key;
    END IF;

    -- Drop the table if it exists to start fresh
    DROP TABLE IF EXISTS stripe_charges CASCADE;

    -- Create table with proper column types
    CREATE TABLE stripe_charges (
        id SERIAL PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        payment_intent_id TEXT,
        charge_id TEXT,
        amount_minor INT NOT NULL,
        currency TEXT NOT NULL,
        status TEXT NOT NULL,
        raw JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Create index if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_sc_by_order') THEN
        CREATE INDEX idx_sc_by_order ON stripe_charges(order_id);
    END IF;

    -- Add unique constraint with a check to avoid duplicate
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'stripe_charges_payment_intent_id_key') THEN
        ALTER TABLE stripe_charges ADD CONSTRAINT stripe_charges_payment_intent_id_key UNIQUE (payment_intent_id);
    END IF;

END$$;
"""

def run():
    try:
        logger.info("Starting stripe_charges table recreation migration...")
        eng = get_engine()
        
        with eng.begin() as conn:
            logger.info("Dropping and recreating stripe_charges table...")
            conn.execute(text(DDL))
        
        print("✅ stripe_charges table recreated successfully with proper column types")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == "__main__":
    run()