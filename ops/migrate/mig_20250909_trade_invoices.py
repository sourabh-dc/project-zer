from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
-- 1) Ensure table exists
CREATE TABLE IF NOT EXISTS trade_invoices (
  id SERIAL PRIMARY KEY,
  tenant_id VARCHAR(100) NOT NULL,
  order_id INTEGER NOT NULL,
  amount_minor BIGINT NOT NULL,
  currency VARCHAR(3) NOT NULL DEFAULT 'GBP',
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  memo TEXT
);

-- 2) Ensure columns exist (ALTERs are idempotent)
ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);

ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS order_id INTEGER;

ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS amount_minor BIGINT;

ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS currency VARCHAR(3);

ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS status VARCHAR(20);

ALTER TABLE trade_invoices
  ADD COLUMN IF NOT EXISTS memo TEXT;

-- 3) Indexes (also idempotent)
CREATE INDEX IF NOT EXISTS idx_trade_invoices_tenant ON trade_invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_trade_invoices_created ON trade_invoices(created_at);
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))
    print("✅ trade_invoices table ready / upgraded")

if __name__ == "__main__":
    run()