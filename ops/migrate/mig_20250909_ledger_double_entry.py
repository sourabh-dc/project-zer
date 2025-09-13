from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
ALTER TABLE ledger_entries
  ADD COLUMN IF NOT EXISTS account       VARCHAR(40),
  ADD COLUMN IF NOT EXISTS site_id       VARCHAR(100),
  ADD COLUMN IF NOT EXISTS store_id      VARCHAR(100);

-- entry_type existed before, but ensure it's present (dev safety)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='ledger_entries' AND column_name='entry_type'
  ) THEN
    ALTER TABLE ledger_entries ADD COLUMN entry_type VARCHAR(10) DEFAULT 'debit';
  END IF;
END$$;

-- Backfill legacy rows (single-entry era) so new writes don't fail comparisons
UPDATE ledger_entries
   SET account = COALESCE(account, 'CostCentreSpend'),
       entry_type = COALESCE(entry_type, 'debit')
 WHERE account IS NULL OR entry_type IS NULL;
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))
    print("✅ Migration applied: ledger_entries upgraded for double-entry.")

if __name__ == "__main__":
    run()