# services/entry/main.py
from fastapi import FastAPI, Body, HTTPException, Query
from pydantic import BaseModel
import os, redis, secrets, time
from datetime import timedelta, datetime
from sqlalchemy import text
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.events.integration import publish_entry_code_generated

SERVICE_NAME = "entry"
app = FastAPI(title="ZeroQue Entry Service", version="0.4.0")

# ---- config ----
TTL_MIN = int(os.getenv("ENTRY_CODE_TTL_MINUTES", "15"))
RL_SEC  = int(os.getenv("ENTRY_RATE_LIMIT_SEC", "1"))
STATUS_ENABLED = os.getenv("ENTRY_STATUS_ENABLED", "0") in ("1", "true", "True")

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

# ---- payloads ----
class IssueCodePayload(BaseModel):
    tenant_id: str
    site_id: str
    store_id: str
    user_id: str

class ValidateCodePayload(BaseModel):
    code: str

# ---- DB helpers ----
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
    row = db.execute(text("""
        SELECT COALESCE(SUM(remaining_minor),0)
        FROM approval_requests
        WHERE cost_centre_id=:cc AND status='approved' AND (user_scope_id IS NULL OR user_scope_id=:u)
    """), {"cc": cost_centre_id, "u": user_id}).first()
    return int(row[0] or 0)

# ---- keys ----
def _fwd_key(tenant_id, site_id, store_id, user_id, code):
    return f"entry:{tenant_id}:{site_id}:{store_id}:{user_id}:{code}"

def _rev_key(code):
    return f"entry_rev:{code}"

def _rl_key(tenant_id, site_id, store_id, user_id):
    return f"entry:rl:{tenant_id}:{site_id}:{store_id}:{user_id}"

# ---- endpoints ----
@app.post("/entry/issue-code")
def issue_code(payload: IssueCodePayload = Body(...)):
    r = get_redis()
    # simple per-user rate limit
    rlk = _rl_key(payload.tenant_id, payload.site_id, payload.store_id, payload.user_id)
    if not r.set(rlk, "1", nx=True, ex=RL_SEC):
        # 429 style response with hint
        # Rate limited - no event publishing for now
        
        return {"allowed": False, "reason": "rate_limited", "retry_after_seconds": RL_SEC}

    with SessionLocal() as db:
        cc_id = _user_primary_cost_centre(db, payload.user_id)
        if not cc_id:
            raise HTTPException(status_code=400, detail="User has no cost centre")
        snap = _budget_snapshot(db, cc_id)
        if not snap:
            raise HTTPException(status_code=400, detail="No budget configured for user's cost centre")

        remaining = snap["limit_minor"] - snap["spent_minor"]
        if snap["hard_block"] and remaining <= 0:
            apr = _get_approval_remaining_for_entry(db, cc_id, payload.user_id)
            if apr <= 0:
                return {
                    "allowed": False,
                    "reason": "overspend",
                    "remaining_minor": remaining,
                    "currency": snap["currency"]
                }

        # generate 6-digit code
        code = f"{secrets.randbelow(1_000_000):06d}"
        fwd = _fwd_key(payload.tenant_id, payload.site_id, payload.store_id, payload.user_id, code)
        rev = _rev_key(code)
        ttl = int(timedelta(minutes=TTL_MIN).total_seconds())

        # write forward + reverse atomically-ish
        # set forward first, then reverse; both with same TTL
        pipe = r.pipeline()
        pipe.set(fwd, "1", ex=ttl)
        pipe.set(rev, fwd, ex=ttl)
        pipe.execute()

    # Code generated - no event publishing for now

        return {"allowed": True, "code": code, "ttl_minutes": TTL_MIN}

@app.post("/entry/validate-code")
def validate_code(payload: ValidateCodePayload = Body(...)):
    r = get_redis()
    rev = _rev_key(payload.code)
    fwd = r.get(rev)
    if not fwd:
        return {"valid": False, "reason": "unknown_or_expired"}

    fwd = fwd.decode("utf-8")
    exists = r.get(fwd)
    if not exists:
        # reverse exists but forward expired (race) → clean up reverse
        r.delete(rev)
        return {"valid": False, "reason": "expired"}

    # consume both keys
    pipe = r.pipeline()
    pipe.delete(fwd)
    pipe.delete(rev)
    pipe.execute()

    # Code validated - no event publishing for now

    # optionally include context back (off by default)
    include_ctx = os.getenv("ENTRY_VALIDATE_INCLUDE_CONTEXT", "0") in ("1","true","True")
    if include_ctx:
        # entry:{tenant}:{site}:{store}:{user}:{code}
        try:
            _, tenant_id, site_id, store_id, user_id, _ = fwd.split(":", 5)
            return {"valid": True, "consumed": True,
                    "context": {"tenant_id": tenant_id, "site_id": site_id, "store_id": store_id, "user_id": user_id}}
        except Exception:
            pass

    return {"valid": True, "consumed": True}

@app.get("/entry/status")
def entry_status(code: str = Query(...)):
    if not STATUS_ENABLED:
        # behave like not found when disabled
        raise HTTPException(status_code=404, detail="not found")
    r = get_redis()
    fwd = r.get(_rev_key(code))
    if not fwd:
        return {"exists": False}
    parts = fwd.decode("utf-8").split(":")
    # entry:{tenant}:{site}:{store}:{user}:{code}
    if len(parts) != 6:
        return {"exists": True}
    return {
        "exists": True,
        "tenant_id": parts[1],
        "site_id": parts[2],
        "store_id": parts[3],
        "user_id": parts[4]
    }