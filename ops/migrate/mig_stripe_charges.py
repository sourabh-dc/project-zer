from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
-- one Stripe customer per tenant
ALTER TABLE stripe_charges ADD COLUMN IF NOT EXISTS site_id TEXT;
ALTER TABLE stripe_charges ADD COLUMN IF NOT EXISTS payment_intent_id TEXT;
ALTER TABLE stripe_charges ADD COLUMN IF NOT EXISTS charge_id TEXT;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE indexname='stripe_charges_pi_uidx'
  ) THEN
    CREATE UNIQUE INDEX stripe_charges_pi_uidx ON stripe_charges(payment_intent_id);
  END IF;
END$$;
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