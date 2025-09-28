from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
  id               BIGSERIAL PRIMARY KEY,
  key              TEXT NOT NULL,
  tenant_id        TEXT NULL,
  method           TEXT NOT NULL,
  path             TEXT NOT NULL,
  request_hash     TEXT NULL,
  response_status  INT  NOT NULL,
  response_body    JSONB NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_idem_lookup
  ON idempotency_keys (key, COALESCE(tenant_id, ''), method, path);
CREATE INDEX IF NOT EXISTS idx_idem_created_at
  ON idempotency_keys (created_at);
"""

if __name__ == "__main__":
    eng = get_engine()
    with eng.begin() as conn:
        for stmt in DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
    print("idempotency_keys table ready ✅")