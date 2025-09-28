from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
  id               BIGSERIAL PRIMARY KEY,
  key              TEXT NOT NULL,
  tenant_id        TEXT NULL,
  method           TEXT NOT NULL,
  path             TEXT NOT NULL,
  request_hash     TEXT NOT NULL,
  response_status  INT  NOT NULL,
  response_body    JSONB NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

DDL_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_idem_scope
  ON idempotency_keys(key, method, path, COALESCE(tenant_id, ''::text));
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL_TABLE))
        conn.execute(text(DDL_INDEX))
    print("✅ idempotency_keys ready (table + index)")

if __name__ == "__main__":
    run()