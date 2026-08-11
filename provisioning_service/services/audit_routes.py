"""
Audit & Confirmation API — Phase 5

Append-only audit trail with plain-English confirmation summaries.
Every access change, approval decision, and confirmation is preserved.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import AuditEntry, ConfirmationSnapshot, UserApprovalControl, User
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization

router = APIRouter(prefix="/audit", tags=["audit"])


# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════

class AuditEntryResponse(BaseModel):
    audit_id: str
    event_type: str
    actor_user_id: Optional[str] = None
    affected_user_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    field_changed: Optional[str] = None
    reason: Optional[str] = None
    confirmation_summary: Optional[str] = None
    created_at: str


class AuditListResponse(BaseModel):
    entries: List[AuditEntryResponse] = Field(default_factory=list)


class ConfirmationRequest(BaseModel):
    """Request to generate + record a plain-English confirmation for a user's access."""
    user_id: str
    role_code: Optional[str] = None
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    max_transaction_minor: Optional[int] = None
    max_period_minor: Optional[int] = None
    period_type: Optional[str] = None
    escalation_user_id: Optional[str] = None
    effective_to: Optional[date] = None


class ConfirmationSummaryResponse(BaseModel):
    user_id: str
    display_name: Optional[str] = None
    job_title: Optional[str] = None
    job_function: Optional[str] = None
    role_code: Optional[str] = None
    scope_description: Optional[str] = None
    transaction_limit: Optional[str] = None
    period_limit: Optional[str] = None
    effective_until: Optional[str] = None
    escalation: Optional[str] = None
    plain_english_summary: str
    snapshot_id: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _generate_summary_text(
    user: User,
    role_code: Optional[str],
    scope_desc: Optional[str],
    tx_limit: Optional[int],
    period_limit: Optional[int],
    period_type: Optional[str],
    escalation_name: Optional[str],
    effective_to: Optional[date],
) -> str:
    """Generate a plain-English confirmation summary."""
    name = user.display_name or "This user"
    job = user.display_job_title or ""
    func = user.job_function or ""

    parts = [f"{name}"]
    if job:
        parts.append(f", {job}")
    if func:
        fn_display = func.replace("_", " ").title()
        parts.append(f", within {fn_display}")

    parts.append(f", can ")

    if role_code == "approver":
        parts.append("approve requests")
    elif role_code == "requester":
        parts.append("request products")
    elif role_code == "requester_and_approver":
        parts.append("request products and approve requests")
    elif role_code:
        parts.append(f"perform {role_code.replace('_', ' ')} activities")

    if scope_desc:
        parts.append(f" at {scope_desc}")
    if tx_limit:
        parts.append(f", up to £{tx_limit / 100:,.2f} per transaction")
    if period_limit and period_type:
        parts.append(f" and £{period_limit / 100:,.2f} per {period_type}")
    if effective_to:
        parts.append(f", until {effective_to.strftime('%d %B %Y')}")
    if escalation_name:
        parts.append(f". Requests above authority route to {escalation_name}")

    if role_code in ("approver", "requester_and_approver"):
        parts.append(". Cannot approve own requests.")

    return "".join(parts) + "."


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.get("", response_model=AuditListResponse)
async def list_audit_entries(
    tenant_id: str = Query(...),
    affected_user_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("audit.view")),
):
    """Query audit trail. Append-only — entries are never modified."""
    q = db.query(AuditEntry).filter(AuditEntry.tenant_id == tenant_id)
    if affected_user_id:
        q = q.filter(AuditEntry.affected_user_id == affected_user_id)
    if event_type:
        q = q.filter(AuditEntry.event_type == event_type)

    entries = q.order_by(AuditEntry.created_at.desc()).limit(limit).all()
    return AuditListResponse(entries=[
        AuditEntryResponse(
            audit_id=str(e.audit_id),
            event_type=e.event_type,
            actor_user_id=str(e.actor_user_id) if e.actor_user_id else None,
            affected_user_id=str(e.affected_user_id) if e.affected_user_id else None,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            field_changed=e.field_changed,
            reason=e.reason,
            confirmation_summary=e.confirmation_summary,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in entries
    ])


@router.post("/confirm-access", response_model=ConfirmationSummaryResponse)
async def confirm_access(
    req: ConfirmationRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """
    Generate a plain-English confirmation summary, save it as an audit
    entry + confirmation snapshot, and return it to the admin.

    This implements the Step 6 (Confirmation) of the setup journey.
    On the frontend, the admin reviews this summary and clicks confirm.
    That confirmation becomes part of the audit history.
    """
    claims = ctx
    tenant_id = claims.get("tenant_id")
    actor_id = claims.get("sub")

    # ── Look up user ──────────────────────────────────────────────
    user = db.query(User).filter(User.user_id == req.user_id).first()
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    # ── Build scope description ──────────────────────────────────
    scope_desc = None
    if req.scope_type and req.scope_id and req.scope_type != "organisation":
        from provisioning_service.Models import Site, CostCentre, OrgUnit
        if req.scope_type == "site":
            obj = db.query(Site).filter(Site.site_id == req.scope_id).first()
            scope_desc = obj.name if obj else req.scope_id
        elif req.scope_type == "cost_centre":
            obj = db.query(CostCentre).filter(CostCentre.cost_centre_id == req.scope_id).first()
            scope_desc = f"{obj.name} cost centre" if obj else req.scope_id
        elif req.scope_type == "department":
            obj = db.query(OrgUnit).filter(OrgUnit.org_unit_id == req.scope_id).first()
            scope_desc = f"{obj.name} department" if obj else req.scope_id
    elif req.scope_type == "organisation":
        scope_desc = "the entire organisation"

    # ── Look up escalation name ──────────────────────────────────
    escalation_name = None
    if req.escalation_user_id:
        esc_user = db.query(User).filter(User.user_id == req.escalation_user_id).first()
        escalation_name = esc_user.display_name if esc_user else None

    # ── Generate summary ─────────────────────────────────────────
    summary = _generate_summary_text(
        user=user,
        role_code=req.role_code,
        scope_desc=scope_desc,
        tx_limit=req.max_transaction_minor,
        period_limit=req.max_period_minor,
        period_type=req.period_type,
        escalation_name=escalation_name,
        effective_to=req.effective_to,
    )

    # ── Create audit entry ───────────────────────────────────────
    audit = AuditEntry(
        audit_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_type="confirmation",
        actor_user_id=actor_id,
        affected_user_id=req.user_id,
        resource_type="user_profile",
        resource_id=req.user_id,
        confirmation_summary=summary,
        reason="Access confirmation generated during user setup",
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.flush()

    # ── Create confirmation snapshot ─────────────────────────────
    snapshot = ConfirmationSnapshot(
        snapshot_id=uuid.uuid4(),
        tenant_id=tenant_id,
        audit_id=audit.audit_id,
        user_id=req.user_id,
        role_code=req.role_code,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        max_transaction_minor=req.max_transaction_minor,
        max_period_minor=req.max_period_minor,
        period_type=req.period_type,
        escalation_user_id=req.escalation_user_id,
        effective_to=req.effective_to,
        summary_text=summary,
        created_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.commit()

    return ConfirmationSummaryResponse(
        user_id=str(user.user_id),
        display_name=user.display_name,
        job_title=user.display_job_title,
        job_function=user.job_function,
        role_code=req.role_code,
        scope_description=scope_desc,
        transaction_limit=f"£{req.max_transaction_minor / 100:,.2f}" if req.max_transaction_minor else None,
        period_limit=f"£{req.max_period_minor / 100:,.2f} per {req.period_type}" if req.max_period_minor else None,
        effective_until=req.effective_to.isoformat() if req.effective_to else None,
        escalation=escalation_name,
        plain_english_summary=summary,
        snapshot_id=str(snapshot.snapshot_id),
    )
