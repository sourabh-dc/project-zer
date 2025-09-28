# ops/migrations/migration.py
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db

def run():
    eng = get_engine()
    init_db()
    with eng.begin() as conn:
        # --- 1) stripe_charges.receipt_url (nullable text) ---
        conn.execute(text("""
            ALTER TABLE stripe_charges
            ADD COLUMN IF NOT EXISTS receipt_url TEXT
        """))

        # --- 2) trade_invoices.invoice_code (optional human-facing code) ---
        conn.execute(text("""
            ALTER TABLE trade_invoices
            ADD COLUMN IF NOT EXISTS invoice_code TEXT
        """))
        # keep it unique when present
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'trade_invoices_invoice_code_uidx'
                ) THEN
                    CREATE UNIQUE INDEX trade_invoices_invoice_code_uidx
                    ON trade_invoices (invoice_code)
                    WHERE invoice_code IS NOT NULL;
                END IF;
            END$$;
        """))

        # --- 3) trade_invoice_lines tax columns ---
        conn.execute(text("""
            ALTER TABLE trade_invoice_lines
            ADD COLUMN IF NOT EXISTS tax_minor BIGINT DEFAULT 0
        """))
        conn.execute(text("""
            ALTER TABLE trade_invoice_lines
            ADD COLUMN IF NOT EXISTS tax_code TEXT
        """))

        # --- 4) webhook idempotency: processed Stripe events ---
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stripe_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        # --- 5) (optional) ensure export fields exist on trade_invoices ---
        conn.execute(text("""
            ALTER TABLE trade_invoices
            ADD COLUMN IF NOT EXISTS export_batch_id TEXT
        """))
        conn.execute(text("""
            ALTER TABLE trade_invoices
            ADD COLUMN IF NOT EXISTS exported_at TIMESTAMPTZ
        """))
        conn.execute(text("""
            ALTER TABLE trade_invoices
            ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ
        """))

    print("Migration completed.")

if __name__ == "__main__":
    run()