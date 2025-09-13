from zeroque_common.db.session import get_engine
from sqlalchemy import text
eng = get_engine()
with eng.begin() as conn:
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        id_key TEXT PRIMARY KEY,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        body_hash TEXT NOT NULL,
        status_code INT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )"""))
print("ok")