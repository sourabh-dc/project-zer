# ops/migrate/mig_catalog_baseline.py
from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
-- Ensure products exists with updated_at
CREATE TABLE IF NOT EXISTS products (
  sku          TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  description  TEXT NULL,
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NULL
);

-- Ensure prices exists with updated_at
CREATE TABLE IF NOT EXISTS prices (
  id           BIGSERIAL PRIMARY KEY,
  sku          TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
  currency     CHAR(3) NOT NULL,
  unit_minor   INTEGER NOT NULL,
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NULL,
  UNIQUE (sku, currency)
);

-- Ensure inventory exists (current on-hand per store/SKU)
CREATE TABLE IF NOT EXISTS inventory (
  store_id     TEXT NOT NULL,
  sku          TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
  qty          INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (store_id, sku)
);

-- Ensure movements table exists (append-only)
CREATE TABLE IF NOT EXISTS inventory_movements (
  id           BIGSERIAL PRIMARY KEY,
  store_id     TEXT NOT NULL,
  sku          TEXT NOT NULL,
  delta        INTEGER NOT NULL,
  reason       TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Backfill missing columns if table already existed
ALTER TABLE products  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL;
ALTER TABLE prices    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NULL;
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        for stmt in [s.strip() for s in DDL.split(";\n") if s.strip()]:
            conn.execute(text(stmt))
    print("✅ catalog baseline ready (products/prices/inventory/movements)")

if __name__ == "__main__":
    run()