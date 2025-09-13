# services/approvals/main.py
from fastapi import FastAPI, Body, Path, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import text
from datetime import datetime
from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.notifications.notifier import (
    notify_manager_new_approval,
    notify_manager_resolution,
)

SERVICE_NAME="approvals"
app = FastAPI(title="ZeroQue Approvals Service", version="0.9.0")

@app.on_event("startup")
def on_startup():
    get_engine(); init_db()

@app.get("/health")
def health(): return {"status":"ok","service":SERVICE_NAME}

@app.get("/readiness")
def readiness(): return {"service":SERVICE_NAME,"db":check_db(),"redis":True}

# -------- Models --------
class CreateApproval(BaseModel):
    tenant_id: str
    cost_centre_id: str
    requester_user_id: str
    user_scope_id: Optional[str] = None
    currency: str = "GBP"
    amount_minor: int
    notes: Optional[str] = None
    expires_at: Optional[datetime] = None

class Approve(BaseModel):
    manager_user_id: str

# -------- Helpers --------
def _approver_list(db, cost_centre_id: str, amount_minor: int) -> List[str]:
    approvers: List[str] = []
    base = db.execute(text("""
        SELECT manager_user_id FROM cost_centres WHERE cost_centre_id=:cc
    """), {"cc": cost_centre_id}).first()
    if base and base[0]:
        approvers.append(base[0])

    rows = db.execute(text("""
        SELECT approver_user_id, min_minor
          FROM approval_rules
         WHERE cost_centre_id=:cc AND min_minor <= :amt
         ORDER BY min_minor ASC
    """), {"cc": cost_centre_id, "amt": amount_minor}).all()
    for r in rows:
        if r[0] not in approvers:
            approvers.append(r[0])
    return approvers

# -------- Endpoints --------
@app.post("/approvals/requests")
def create(req: CreateApproval = Body(...)):
    if req.amount_minor <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")
    with SessionLocal() as db:
        row = db.execute(text("""
            INSERT INTO approval_requests(
                tenant_id, cost_centre_id, requester_user_id, user_scope_id,
                currency, amount_minor, remaining_minor, status, notes, expires_at, created_at
            )
            VALUES(:t,:cc,:ru,:us,:cur,:amt,:amt,'pending',:n,:exp,NOW())
            RETURNING id
        """), {
            "t": req.tenant_id, "cc": req.cost_centre_id, "ru": req.requester_user_id,
            "us": req.user_scope_id, "cur": req.currency, "amt": req.amount_minor,
            "n": req.notes, "exp": req.expires_at
        }).first()
        a_id = int(row[0])
        db.commit()

        approvers = _approver_list(db, req.cost_centre_id, req.amount_minor)

        notify_manager_new_approval(req.tenant_id, {
            "id": a_id,
            "tenant_id": req.tenant_id,
            "cost_centre_id": req.cost_centre_id,
            "requester_user_id": req.requester_user_id,
            "user_scope_id": req.user_scope_id,
            "currency": req.currency,
            "amount_minor": req.amount_minor,
            "notes": req.notes,
            "expires_at": (req.expires_at.isoformat() if req.expires_at else None),
            "status": "pending"
        }, approvers=approvers)

        return {"id": a_id, "status": "pending"}

@app.post("/approvals/requests/{approval_id}/approve")
def approve(approval_id: int = Path(...), payload: Approve = Body(...)):
    with SessionLocal() as db:
        row = db.execute(text("SELECT tenant_id, status FROM approval_requests WHERE id=:id"), {"id": approval_id}).first()
        if not row: raise HTTPException(status_code=404, detail="not found")
        tenant_id, status = row[0], row[1]

        if status == "approved":
            return {"id": approval_id, "status": "approved", "idempotent": True}
        if status == "denied":
            raise HTTPException(status_code=409, detail="already denied")
        if status != "pending":
            raise HTTPException(status_code=400, detail="not pending")

        db.execute(text("""
            UPDATE approval_requests
               SET status='approved', approved_by=:m, approved_at=:now
             WHERE id=:id
        """), {"m": payload.manager_user_id, "now": datetime.utcnow(), "id": approval_id})
        db.commit()

        notify_manager_resolution(tenant_id, approval_id, "approved", payload.manager_user_id)
        return {"id": approval_id, "status": "approved"}

@app.post("/approvals/requests/{approval_id}/deny")
def deny(approval_id: int = Path(...), payload: Approve = Body(...)):
    with SessionLocal() as db:
        row = db.execute(text("SELECT tenant_id, status FROM approval_requests WHERE id=:id"), {"id": approval_id}).first()
        if not row: raise HTTPException(status_code=404, detail="not found")
        tenant_id, status = row[0], row[1]

        if status == "denied":
            return {"id": approval_id, "status": "denied", "idempotent": True}
        if status == "approved":
            raise HTTPException(status_code=409, detail="already approved")
        if status != "pending":
            raise HTTPException(status_code=400, detail="not pending")

        db.execute(text("""
            UPDATE approval_requests
               SET status='denied', approved_by=:m, approved_at=:now
             WHERE id=:id
        """), {"m": payload.manager_user_id, "now": datetime.utcnow(), "id": approval_id})
        db.commit()

        notify_manager_resolution(tenant_id, approval_id, "denied", payload.manager_user_id)
        return {"id": approval_id, "status": "denied"}

@app.get("/approvals/requests")
def list_requests(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    include_expired: bool = Query(False),
    limit: int = Query(50)
):
    q = """
      SELECT id, tenant_id, cost_centre_id, requester_user_id, user_scope_id, currency,
             amount_minor, remaining_minor, status, approved_by, approved_at, created_at,
             notes, expires_at
        FROM approval_requests
       WHERE tenant_id=:t
    """
    params = {"t": tenant_id}
    if status:
        q += " AND status=:s"; params["s"] = status
    if cost_centre_id:
        q += " AND cost_centre_id=:cc"; params["cc"] = cost_centre_id
    if user_id:
        q += " AND user_scope_id=:u"; params["u"] = user_id
    if not include_expired:
        q += " AND (expires_at IS NULL OR expires_at > NOW())"
    q += " ORDER BY id DESC LIMIT :l"
    params["l"] = limit

    with SessionLocal() as db:
        rows = db.execute(text(q), params).all()
        return [{
          "id": int(r[0]), "tenant_id": r[1], "cost_centre_id": r[2], "requester_user_id": r[3],
          "user_scope_id": r[4], "currency": r[5], "amount_minor": int(r[6]), "remaining_minor": int(r[7] or 0),
          "status": r[8], "approved_by": r[9],
          "approved_at": (str(r[10]) if r[10] else None),
          "created_at": str(r[11]),
          "notes": r[12],
          "expires_at": (str(r[13]) if r[13] else None),
        } for r in rows]