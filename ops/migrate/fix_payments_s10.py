# fix_migration.py
from sqlalchemy import text
from zeroque_common.db.session import get_engine

def fix_columns():
    eng = get_engine()
    with eng.begin() as conn:
        # Add missing columns
        conn.execute(text("""
            ALTER TABLE stripe_charges
  ADD COLUMN IF NOT EXISTS site_id TEXT;

CREATE INDEX IF NOT EXISTS idx_sc_by_site ON stripe_charges(site_id);
        """))
    print("✅ Added missing columns to trade_invoices")

if __name__ == "__main__":
    fix_columns()