from fastapi import FastAPI, Body, HTTPException
from pydantic import BaseModel
import os, redis
from datetime import timedelta, datetime
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal

SERVICE_NAME = "entry"
app = FastAPI(title="ZeroQue Entry Service", version="0.3.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

def get_redis():
    return redis.from_url(os.getenv("REDIS_URL", "redis://localhost:4000/0"))

@app.get("/health")
def health(): return {"status":"ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    try:
        get_redis().ping(); r_ok = True
    except Exception:
        r_ok = False
    return {"service": SERVICE_NAME, "db": check_db(), "redis": r_ok}

class IssueCodePayload(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    user_id: str

class ValidateCodePayload(BaseModel):
    code: str

def _user_primary_cost_centre(db, user_id: str):
    row = db.execute(text("""
        SELECT cost_centre_id FROM user_cost_centres
        WHERE user_id=:u
        ORDER BY id ASC
        LIMIT 1
    """), {"u": user_id}).first()
    return row[0] if row else None

def _budget_snapshot(db, cost_centre_id: str):
    row = db.execute(text("""
        SELECT b.limit_minor, b.spent_minor, b.currency, b.hard_block
        FROM budgets b
        WHERE b.cost_centre_id=:cc
        ORDER BY b.budget_id DESC
        LIMIT 1
    """), {"cc": cost_centre_id}).first()
    if not row:
        return None
    return {"limit_minor": int(row[0]), "spent_minor": int(row[1]), "currency": row[2], "hard_block": bool(row[3])}

def _get_approval_remaining_for_entry(db, cost_centre_id: str, user_id: str) -> int:
    # Sum approved remaining for CC-level or user-scoped approvals
    row = db.execute(text("""
        SELECT COALESCE(SUM(remaining_minor),0)
        FROM approval_requests
        WHERE cost_centre_id=:cc AND status='approved' AND (user_scope_id IS NULL OR user_scope_id=:u)
    """), {"cc": cost_centre_id, "u": user_id}).first()
    return int(row[0] or 0)

@app.post("/entry/issue-code")
def issue_code(payload: IssueCodePayload = Body(...)):
    with SessionLocal() as db:
        cc_id = _user_primary_cost_centre(db, payload.user_id)
        if not cc_id:
            raise HTTPException(status_code=400, detail="User has no cost centre")
        snap = _budget_snapshot(db, cc_id)
        if not snap:
            raise HTTPException(status_code=400, detail="No budget configured for user's cost centre")
        remaining = snap["limit_minor"] - snap["spent_minor"]
        if snap["hard_block"] and remaining <= 0:
            # check approvals
            apr = _get_approval_remaining_for_entry(db, cc_id, payload.user_id)
            if apr > 0:
                return {"allowed": True, "code": f"{datetime.utcnow().timestamp():.0f}"[-6:], "ttl_minutes": 15, "note": "allowed via approval"}
            return {"allowed": False, "reason": "overspend", "remaining_minor": remaining, "currency": snap["currency"]}
        # issue 6-digit code, valid 15 minutes
        code = f"{datetime.utcnow().timestamp():.0f}"[-6:]
        key = f"entry:{payload.tenant_id}:{payload.site_id}:{payload.store_id}:{payload.user_id}:{code}"
        r = get_redis()
        r.setex(key, int(timedelta(minutes=15).total_seconds()), "1")
        return {"allowed": True, "code": code, "ttl_minutes": 15}

@app.post("/entry/validate-code")
def validate_code(payload: ValidateCodePayload = Body(...)):
    r = get_redis()
    # brute scan small space (dev only); in prod you’d store reverse index
    pattern = f"entry:*:*:*:*:{payload.code}"
    for k in r.scan_iter(match=pattern):
        if r.get(k):
            r.delete(k)  # consume
            return {"valid": True, "consumed": True}
    return {"valid": False}