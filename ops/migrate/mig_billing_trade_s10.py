from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS trade_invoices (
  id SERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  site_id TEXT,
  order_id TEXT,
  amount_minor INT NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', -- draft|posted|exported
  posted_at TIMESTAMPTZ,
  exported_at TIMESTAMPTZ,
  export_batch_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add external human-readable code if you want (unique)
ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS invoice_code TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_trade_invoice_code ON trade_invoices(invoice_code);

-- Ensure columns (no-op if they exist already)
ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS order_id TEXT,
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS exported_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS export_batch_id TEXT;

-- Lines table (keeps existing if already present)
CREATE TABLE IF NOT EXISTS trade_invoice_lines (
  id SERIAL PRIMARY KEY,
  invoice_id INT NOT NULL REFERENCES trade_invoices(id) ON DELETE CASCADE,
  sku TEXT NOT NULL,
  qty INT NOT NULL,
  unit_price_minor INT NOT NULL,
  currency TEXT NOT NULL
);

-- Tiny preferences switch (per-tenant)
CREATE TABLE IF NOT EXISTS payment_preferences (
  tenant_id TEXT PRIMARY KEY,
  method TEXT NOT NULL CHECK (method IN ('stripe','trade')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ti_tenant_created ON trade_invoices(tenant_id, created_at);
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