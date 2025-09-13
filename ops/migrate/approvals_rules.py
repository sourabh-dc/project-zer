from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
CREATE TABLE IF NOT EXISTS approval_rules (
  id SERIAL PRIMARY KEY,
  cost_centre_id TEXT NOT NULL,
  min_minor INT NOT NULL DEFAULT 0,   -- threshold in minor units (eg pence)
  approver_user_id TEXT NOT NULL,
  UNIQUE(cost_centre_id, min_minor, approver_user_id)
);
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))
    print("✅ approval_rules table ready")

if __name__ == "__main__":
    run()