from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
-- one Stripe customer per tenant
-- stripe_events for webhook idempotency
CREATE TABLE IF NOT EXISTS stripe_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- trade_invoices extra fields (safe add-if-missing)
ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS site_id TEXT;
ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;
ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS exported_at TIMESTAMPTZ;
ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS export_batch_id TEXT;
ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS invoice_code TEXT;

-- trade_invoice_lines table (if not present)
CREATE TABLE IF NOT EXISTS trade_invoice_lines (
  id SERIAL PRIMARY KEY,
  invoice_id INT NOT NULL REFERENCES trade_invoices(id) ON DELETE CASCADE,
  sku TEXT NOT NULL,
  qty INT NOT NULL,
  unit_price_minor INT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'GBP',
  tax_minor INT NOT NULL DEFAULT 0,
  tax_code TEXT
);

-- stripe_charges extra fields (reports/webhook)
ALTER TABLE stripe_charges ADD COLUMN IF NOT EXISTS site_id TEXT;
ALTER TABLE stripe_charges ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
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