# dev_seed_cc_budget.py
from sqlalchemy import text
from zeroque_common.db.session import get_engine

TENANT   = "tenant-abc"
USER     = "user-001"    # your SHOPPER_ID
CC_ID    = "cc-001"
MANAGER  = "manager-001"
CURRENCY = "GBP"
LIMIT    = 100_000       # £1000.00 in minor
HARD_BLOCK = True

def main():
    eng = get_engine()
    with eng.begin() as conn:
        # cost centre
        conn.execute(text("""
            INSERT INTO cost_centres (cost_centre_id, tenant_id, manager_user_id, name)
            VALUES (:cc, :t, :mgr, 'Default CC')
            ON CONFLICT (cost_centre_id) DO NOTHING
        """), {"cc": CC_ID, "t": TENANT, "mgr": MANAGER})

        # user → cost centre mapping
        conn.execute(text("""
            INSERT INTO user_cost_centres (user_id, cost_centre_id)
            VALUES (:u, :cc)
            ON CONFLICT DO NOTHING
        """), {"u": USER, "cc": CC_ID})

        # budget snapshot
        conn.execute(text("""
            INSERT INTO budgets (cost_centre_id, limit_minor, spent_minor, currency, hard_block)
            VALUES (:cc, :lim, 0, :cur, :hb)
        """), {"cc": CC_ID, "lim": LIMIT, "cur": CURRENCY, "hb": HARD_BLOCK})

        # OPTIONAL: pre-approval (500.00 cover) — comment out if you don’t want it
        conn.execute(text("""
            INSERT INTO approval_requests(
              tenant_id, cost_centre_id, requester_user_id, user_scope_id,
              currency, amount_minor, remaining_minor, status, notes, created_at, approved_by, approved_at
            )
            VALUES (
              :t, :cc, :u, :u,
              :cur, 50000, 50000, 'approved', 'Dev cover', NOW(), :mgr, NOW()
            )
        """), {"t": TENANT, "cc": CC_ID, "u": USER, "cur": CURRENCY, "mgr": MANAGER})

    print("✅ Seeded cost centre, mapping, budget (and optional approval).")

if __name__ == "__main__":
    main()