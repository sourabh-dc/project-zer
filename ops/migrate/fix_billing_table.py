# fix_migration.py
from sqlalchemy import text
from zeroque_common.db.session import get_engine

def fix_columns():
    eng = get_engine()
    with eng.begin() as conn:
        # Add missing columns
        conn.execute(text("""
            ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS site_id TEXT;
            ALTER TABLE trade_invoices ADD COLUMN IF NOT EXISTS order_id TEXT;
        """))
    print("✅ Added missing columns to trade_invoices")

if __name__ == "__main__":
    fix_columns()