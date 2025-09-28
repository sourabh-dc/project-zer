from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
-- First check if the table exists and has the basic structure
DO $$
BEGIN
    -- Drop the table if it exists (clean start)
    DROP TABLE IF EXISTS idempotency_keys;
    
    -- Create the table with all required columns
    CREATE TABLE idempotency_keys (
        id SERIAL PRIMARY KEY,
        key VARCHAR(255) NOT NULL,
        tenant_id VARCHAR(255),
        method VARCHAR(10) NOT NULL,
        path VARCHAR(255) NOT NULL,
        response_status INTEGER,
        response_body TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        -- Ensure unique idempotency keys per tenant/method/path combination
        UNIQUE(key, COALESCE(tenant_id, ''), method, path)
    );
    
    RAISE NOTICE 'Idempotency keys table created successfully';
END $$;
"""

def run():
    try:
        logger.info("Starting idempotency_keys migration...")
        eng = get_engine()
        
        with eng.begin() as conn:
            logger.info("Executing DDL...")
            conn.execute(text(DDL))
        
        print("✅ Idempotency keys table created successfully")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == "__main__":
    run()