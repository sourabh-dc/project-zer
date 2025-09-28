from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
-- one Stripe customer per tenant
CREATE TABLE IF NOT EXISTS stripe_customers (
  id SERIAL PRIMARY KEY,
  tenant_id TEXT UNIQUE NOT NULL,
  stripe_customer_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- one row per PaymentIntent/Charge lifecycle (we denormalize a little for convenience)
CREATE TABLE IF NOT EXISTS stripe_charges (
  id SERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  payment_intent_id TEXT UNIQUE,
  charge_id TEXT,
  amount_minor INT NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL,  -- requires_payment_method|requires_confirmation|processing|succeeded|canceled|failed
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sc_by_order ON stripe_charges(order_id);
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