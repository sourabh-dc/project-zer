from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
-- inventory on-hand table (store_id + sku unique)
CREATE TABLE IF NOT EXISTS inventory (
  store_id VARCHAR(100) NOT NULL,
  sku      VARCHAR(100) NOT NULL,
  qty      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (store_id, sku)
);

-- movements audit
CREATE TABLE IF NOT EXISTS inventory_movements (
  id SERIAL PRIMARY KEY,
  store_id VARCHAR(100) NOT NULL,
  sku      VARCHAR(100) NOT NULL,
  delta    INTEGER NOT NULL,
  reason   VARCHAR(40) NOT NULL DEFAULT 'restock',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inv_mov_store ON inventory_movements(store_id, created_at);
CREATE INDEX IF NOT EXISTS idx_inv_mov_sku   ON inventory_movements(sku, created_at);
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))
    print("✅ inventory + movements ready")

if __name__ == "__main__":
    run()