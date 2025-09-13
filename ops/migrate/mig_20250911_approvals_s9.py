from sqlalchemy import text
from zeroque_common.db.session import get_engine

DDL = """
-- notes + expiry + small indexes
ALTER TABLE approval_requests
  ADD COLUMN IF NOT EXISTS notes TEXT,
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- helpful indexes
CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_cc ON approval_requests(cost_centre_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_user ON approval_requests(user_scope_id);
"""

def run():
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(DDL))
    print("✅ Approval requests migration completed successfully")

if __name__ == "__main__":
    run()