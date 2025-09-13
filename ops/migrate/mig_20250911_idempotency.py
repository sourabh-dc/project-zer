from sqlalchemy import text
from zeroque_common.db.session import get_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
  id SERIAL PRIMARY KEY,
  key TEXT NOT NULL,
  tenant_id TEXT,
  method TEXT NOT NULL,
  path TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_status INT NOT NULL,
  response_body JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  tenant_id_or_empty TEXT GENERATED ALWAYS AS (COALESCE(tenant_id, '')) STORED,
  UNIQUE (key, tenant_id_or_empty, method, path)
);

CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency_keys(created_at);
"""

def run():
    try:
        logger.info("Starting idempotency_keys migration...")
        eng = get_engine()
        
        with eng.begin() as conn:
            logger.info("Executing DDL...")
            conn.execute(text(DDL))
        
        print("✅ Idempotency keys table created successfully")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        raise

if __name__ == "__main__":
    run()