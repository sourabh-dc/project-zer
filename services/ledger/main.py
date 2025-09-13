from fastapi import FastAPI, Query
from sqlalchemy import text
from typing import Optional
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal

SERVICE_NAME = "ledger"
app = FastAPI(title="ZeroQue Ledger Service", version="0.6.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

@app.get("/ledger")
def list_ledger(
    tenant_id: str = Query(...),
    account: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    cursor: Optional[int] = Query(None),
    limit: int = Query(100)
):
    with SessionLocal() as db:
        where = ["tenant_id=:t"]
        params = {"t": tenant_id, "l": limit}
        if account:
            where.append("account=:a"); params["a"] = account
        if cost_centre_id:
            where.append("COALESCE(cost_centre_id,'')=COALESCE(:cc,'')"); params["cc"] = cost_centre_id
        if cursor:
            where.append("id < :c"); params["c"] = cursor
        sql = f"""
          SELECT id, account, entry_type, amount_minor, currency, cost_centre_id, site_id, store_id,
                 reference_type, reference_id, description, occurred_at
          FROM ledger_entries
          WHERE {' AND '.join(where)}
          ORDER BY id DESC
          LIMIT :l
        """
        rows = db.execute(text(sql), params).all()
        next_cursor = int(rows[-1][0]) if rows else None
        return {
            "items": [{
              "id": int(r[0]), "account": r[1], "entry_type": r[2], "amount_minor": int(r[3]), "currency": r[4],
              "cost_centre_id": r[5], "site_id": r[6], "store_id": r[7],
              "reference_type": r[8], "reference_id": r[9], "description": r[10], "occurred_at": str(r[11])
            } for r in rows],
            "next_cursor": next_cursor
        }

@app.get("/ledger/balance")
def balance(tenant_id: str = Query(...), cost_centre_id: Optional[str] = Query(None)):
    with SessionLocal() as db:
        if cost_centre_id:
            sql = """
              SELECT account,
                     SUM(CASE WHEN entry_type='debit' THEN amount_minor ELSE 0 END) AS debits,
                     SUM(CASE WHEN entry_type='credit' THEN amount_minor ELSE 0 END) AS credits
              FROM ledger_entries
              WHERE tenant_id=:t AND COALESCE(cost_centre_id,'')=COALESCE(:cc,'')
              GROUP BY account
            """
            params = {"t": tenant_id, "cc": cost_centre_id}
        else:
            sql = """
              SELECT account,
                     SUM(CASE WHEN entry_type='debit' THEN amount_minor ELSE 0 END) AS debits,
                     SUM(CASE WHEN entry_type='credit' THEN amount_minor ELSE 0 END) AS credits
              FROM ledger_entries
              WHERE tenant_id=:t
              GROUP BY account
            """
            params = {"t": tenant_id}

        rows = db.execute(text(sql), params).all()
        return [
            {
                "account": r[0],
                "debits_minor": int(r[1] or 0),
                "credits_minor": int(r[2] or 0),
                "net_minor": int((r[1] or 0) - (r[2] or 0)),
            }
            for r in rows
        ]