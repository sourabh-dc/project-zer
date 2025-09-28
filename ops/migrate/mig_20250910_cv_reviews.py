from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
CREATE TABLE IF NOT EXISTS cv_unknown_item_reviews (
  id SERIAL PRIMARY KEY,
  provider        VARCHAR(40) NOT NULL,
  tenant_id       VARCHAR(100),
  site_id         VARCHAR(100),
  store_id        VARCHAR(100),
  external_sku    VARCHAR(200),   -- as seen from provider
  name            VARCHAR(300),
  qty             INTEGER,
  price_minor     BIGINT,
  payload_json    JSONB,          -- raw item/payload fragment
  status          VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending|resolved|ignored
  mapped_sku      VARCHAR(100),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cv_review_tenant ON cv_unknown_item_reviews(tenant_id, status, created_at);
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))
    print("✅ cv_unknown_item_reviews ready")

if __name__ == "__main__":
    run()