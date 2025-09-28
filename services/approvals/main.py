# services/approvals/main.py
from fastapi import FastAPI, Body, Path, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy import text
from datetime import datetime, timezone
import logging

from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
from zeroque_common.notifications.notifier import (
    notify_manager_new_approval,
    notify_manager_resolution,
)

SERVICE_NAME = "approvals"
app = FastAPI(title="ZeroQue Approvals Service", version="1.0.0")

# ---------- logging ----------
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

# ---------- lifecycle ----------
@app.on_event("startup")
def on_startup():
    get_engine()
    init_db()
    logger.info("service_started", extra={"service": SERVICE_NAME, "version": "1.0.0"})

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": check_db(), "redis": True}

# ---------- payloads ----------
class CreateApproval(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    cost_centre_id: str = Field(..., description="Cost centre against which approval is requested")
    requester_user_id: str = Field(..., description="The user asking for approval")
    user_scope_id: Optional[str] = Field(
        None,
        description="If set, approval can be consumed only by this user; else CC-wide"
    )
    currency: str = Field("GBP", min_length=3, max_length=3)
    amount_minor: int = Field(..., gt=0, description="Requested amount in minor units (e.g., pence)")
    notes: Optional[str] = None
    expires_at: Optional[datetime] = Field(
        None,
        description="UTC expiry; if omitted, approval does not expire"
    )

class Approve(BaseModel):
    manager_user_id: str = Field(..., description="Approver user id")

# ---------- helpers ----------
def _approver_list(db, cost_centre_id: str, amount_minor: int) -> List[str]:
    """
    Build the approver list:
    - CC manager (if present)
    - Any approval_rules that match amount threshold
    """
    approvers: List[str] = []

    base = db.execute(text("""
        SELECT manager_user_id
          FROM cost_centres
         WHERE cost_centre_id = :cc
         LIMIT 1
    """), {"cc": cost_centre_id}).first()
    if base and base[0]:
        approvers.append(base[0])

    rows = db.execute(text("""
        SELECT approver_user_id
          FROM approval_rules
         WHERE cost_centre_id = :cc
           AND min_minor <= :amt
         ORDER BY min_minor ASC
    """), {"cc": cost_centre_id, "amt": amount_minor}).all()
    for r in rows:
        if r[0] not in approvers:
            approvers.append(r[0])

    return approvers

def _utc_now():
    return datetime.now(timezone.utc)

# ---------- endpoints ----------
@app.post("/approvals/requests")
def create(req: CreateApproval = Body(...)):
    # normalize currency
    req.currency = (req.currency or "GBP").upper()

    # validate expires_at (if provided, must be in the future)
    if req.expires_at and req.expires_at <= _utc_now():
        raise HTTPException(status_code=400, detail="expires_at must be in the future")

    with SessionLocal() as db:
        # existence checks (lightweight but useful)
        cc = db.execute(text("""
            SELECT cost_centre_id FROM cost_centres WHERE cost_centre_id=:cc
        """), {"cc": req.cost_centre_id}).first()
        if not cc:
            raise HTTPException(status_code=400, detail="Unknown cost_centre_id")

        try:
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

            approvers = _approver_list(db, req.cost_centre_id, req.amount_minor)
            logger.info("approval_created",
                        extra={"approval_id": a_id, "tenant_id": req.tenant_id,
                               "cc": req.cost_centre_id, "amount_minor": req.amount_minor,
                               "approvers": approvers})

            # best-effort notifications
            try:
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
                    "status": "pending",
                }, approvers=approvers)
            except Exception as e:
                logger.warning("notify_new_approval_failed", extra={"approval_id": a_id, "error": str(e)})

            db.commit()
            return {"id": a_id, "status": "pending"}

        except Exception as e:
            db.rollback()
            logger.exception("approval_create_failed", extra={"tenant_id": req.tenant_id, "cc": req.cost_centre_id})
            raise HTTPException(status_code=500, detail="create_failed")

@app.post("/approvals/requests/{approval_id}/approve")
def approve(approval_id: int = Path(...), payload: Approve = Body(...)):
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT tenant_id, status FROM approval_requests WHERE id=:id
        """), {"id": approval_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        tenant_id, status = row[0], row[1]

        if status == "approved":
            return {"id": approval_id, "status": "approved", "idempotent": True}
        if status == "denied":
            raise HTTPException(status_code=409, detail="already denied")
        if status != "pending":
            raise HTTPException(status_code=400, detail="not pending")

        try:
            db.execute(text("""
                UPDATE approval_requests
                   SET status='approved', approved_by=:m, approved_at=:now
                 WHERE id=:id
            """), {"m": payload.manager_user_id, "now": _utc_now(), "id": approval_id})

            # best-effort notifications
            try:
                notify_manager_resolution(tenant_id, approval_id, "approved", payload.manager_user_id)
            except Exception as e:
                logger.warning("notify_resolution_failed", extra={"approval_id": approval_id, "error": str(e)})

            db.commit()
            logger.info("approval_approved",
                        extra={"approval_id": approval_id, "manager_user_id": payload.manager_user_id})
            return {"id": approval_id, "status": "approved"}

        except Exception:
            db.rollback()
            logger.exception("approval_approve_failed", extra={"approval_id": approval_id})
            raise HTTPException(status_code=500, detail="approve_failed")

@app.post("/approvals/requests/{approval_id}/deny")
def deny(approval_id: int = Path(...), payload: Approve = Body(...)):
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT tenant_id, status FROM approval_requests WHERE id=:id
        """), {"id": approval_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        tenant_id, status = row[0], row[1]

        if status == "denied":
            return {"id": approval_id, "status": "denied", "idempotent": True}
        if status == "approved":
            raise HTTPException(status_code=409, detail="already approved")
        if status != "pending":
            raise HTTPException(status_code=400, detail="not pending")

        try:
            db.execute(text("""
                UPDATE approval_requests
                   SET status='denied', approved_by=:m, approved_at=:now
                 WHERE id=:id
            """), {"m": payload.manager_user_id, "now": _utc_now(), "id": approval_id})

            try:
                notify_manager_resolution(tenant_id, approval_id, "denied", payload.manager_user_id)
            except Exception as e:
                logger.warning("notify_resolution_failed", extra={"approval_id": approval_id, "error": str(e)})

            db.commit()
            logger.info("approval_denied",
                        extra={"approval_id": approval_id, "manager_user_id": payload.manager_user_id})
            return {"id": approval_id, "status": "denied"}

        except Exception:
            db.rollback()
            logger.exception("approval_deny_failed", extra={"approval_id": approval_id})
            raise HTTPException(status_code=500, detail="deny_failed")

@app.get("/approvals/requests")
def list_requests(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None, pattern="^(pending|approved|denied)$"),
    cost_centre_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None, description="Filter by user_scope_id"),
    include_expired: bool = Query(False),
    limit: int = Query(50, ge=1, le=200)
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
        out = [{
          "id": int(r[0]), "tenant_id": r[1], "cost_centre_id": r[2], "requester_user_id": r[3],
          "user_scope_id": r[4], "currency": r[5], "amount_minor": int(r[6]),
          "remaining_minor": int(r[7] or 0), "status": r[8], "approved_by": r[9],
          "approved_at": (r[10].isoformat() if r[10] else None),
          "created_at": r[11].isoformat() if hasattr(r[11], "isoformat") else str(r[11]),
          "notes": r[12],
          "expires_at": (r[13].isoformat() if r[13] else None),
        } for r in rows]

        logger.info("approvals_listed", extra={"tenant_id": tenant_id, "count": len(out)})
        return out