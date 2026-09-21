"""
budget_routes.py
----------------
Company budget caps, cost-centre budget versions, and budget transactions.

Policy gates
------------
All cap-headroom and hard/soft-cap enforcement is delegated to OPA via
require_policy() with enriched resource loaders.  The inline Python checks
(hard_cap > allocated, soft cap without override_reason) have been removed.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    CompanyBudgetCap, CostCentreBudgetVersion, BudgetTransaction,
    FinancialYear, FinancialPeriod, CostCentre, CostCentreAuditEvent,
)
from provisioning_service.Schemas import (
    CompanyBudgetCapCreate, CompanyBudgetCapUpdate,
    CCBudgetVersionCreate, CCBudgetVersionUpdate,
    BudgetReallocationRequest, CCDistributionRequest, CarryForwardRequest,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.core.helpers.resource_loaders import (
    cc_budget_create_resource,
    company_cap_update_resource,
    budget_reallocate_resource,
)
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/budgets", tags=["Budgets"])


# =============================================================================
# COMPANY BUDGET CAP
# =============================================================================

@router.post("/company-caps", status_code=201)
async def create_company_cap(
    req: CompanyBudgetCapCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    policy_result: dict = Depends(require_policy("budget.create_cap")),
):
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    existing = db.query(CompanyBudgetCap).filter(
        CompanyBudgetCap.tenant_id == tenant_id,
        CompanyBudgetCap.year_id == uuid.UUID(req.year_id),
    ).first()
    if existing:
        raise HTTPException(409, "A company budget cap already exists for this year")

    year = db.query(FinancialYear).filter(
        FinancialYear.year_id == uuid.UUID(req.year_id),
        FinancialYear.tenant_id == tenant_id,
    ).first()
    if not year:
        raise HTTPException(404, "Financial year not found")

    cap = CompanyBudgetCap(
        cap_id=uuid.uuid4(),
        tenant_id=tenant_id,
        year_id=uuid.UUID(req.year_id),
        calendar_id=uuid.UUID(req.calendar_id),
        currency=req.currency,
        total_budget_minor=req.total_budget_minor,
        hard_cap=req.hard_cap,
        notes=req.notes,
        created_by=user_id,
    )
    db.add(cap)
    db.commit()
    db.refresh(cap)

    _write_outbox(db, tenant_id, "company_budget_cap.created",
                  {"cap_id": str(cap.cap_id), "year_id": req.year_id,
                   "total_budget_minor": req.total_budget_minor})

    return _cap_dict(cap)


@router.get("/company-caps")
async def list_company_caps(
    year_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(CompanyBudgetCap).filter(CompanyBudgetCap.tenant_id == tenant_id)
    if year_id:
        q = q.filter(CompanyBudgetCap.year_id == uuid.UUID(year_id))
    return {"caps": [_cap_dict(c) for c in q.all()]}


@router.put("/company-caps/{cap_id}")
async def update_company_cap(
    cap_id: str,
    req: CompanyBudgetCapUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    # OPA checks: would_underfund + hard_cap → deny; soft + no override → deny.
    policy_result: dict = Depends(
        require_policy("budget.update_cap", resource_loader=company_cap_update_resource)
    ),
):
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)
    cap = _get_cap_or_404(db, cap_id, tenant_id)

    if req.total_budget_minor is not None:
        cap.total_budget_minor = req.total_budget_minor
    if req.hard_cap is not None:
        cap.hard_cap = req.hard_cap
    if req.notes is not None:
        cap.notes = req.notes

    cap.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cap)

    _write_outbox(db, tenant_id, "company_budget_cap.updated",
                  {"cap_id": cap_id, "total_budget_minor": cap.total_budget_minor,
                   "override_reason": getattr(req, "override_reason", None)})

    return _cap_dict(cap)


# =============================================================================
# COST CENTRE BUDGET VERSIONS
# =============================================================================

@router.post("/cc-versions", status_code=201)
async def create_cc_budget_version(
    req: CCBudgetVersionCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    # OPA checks: hard cap exceeded → deny; soft cap + no override → deny.
    policy_result: dict = Depends(
        require_policy("budget.create_version", resource_loader=cc_budget_create_resource)
    ),
):
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    cc = db.query(CostCentre).filter(
        CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id),
        CostCentre.tenant_id == tenant_id,
        CostCentre.is_active == True,
    ).first()
    if not cc:
        raise HTTPException(404, "Cost centre not found")

    period_id = uuid.UUID(req.period_id) if req.period_id else None

    existing = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == uuid.UUID(req.cost_centre_id),
        CostCentreBudgetVersion.year_id == uuid.UUID(req.year_id),
        CostCentreBudgetVersion.period_id == period_id,
        CostCentreBudgetVersion.status != "closed",
    ).first()
    if existing:
        raise HTTPException(409, "An active budget version already exists for this CC/year/period combination")

    # Increment the company cap's allocated counter (OPA has already validated it).
    cap = db.query(CompanyBudgetCap).filter(
        CompanyBudgetCap.tenant_id == tenant_id,
        CompanyBudgetCap.year_id == uuid.UUID(req.year_id),
    ).first()
    if cap:
        cap.allocated_minor = (cap.allocated_minor or 0) + req.budget_minor

    version = CostCentreBudgetVersion(
        version_id=uuid.uuid4(),
        cost_centre_id=uuid.UUID(req.cost_centre_id),
        year_id=uuid.UUID(req.year_id),
        period_id=period_id,
        tenant_id=tenant_id,
        currency=req.currency,
        budget_minor=req.budget_minor,
        status="active",
        override_reason=req.override_reason,
        created_by=user_id,
    )
    db.add(version)
    db.flush()

    # Record ledger transaction
    _record_txn(db, tenant_id, "allocation", None, version.version_id,
                req.budget_minor, req.currency, user_id, "Initial allocation")

    # "Add year" on an annual version: seed period rows following the CC's
    # usual distribution pattern (even split across that year's periods)
    if period_id is None and cc.period_granularity in ("month", "quarter"):
        periods = db.query(FinancialPeriod).filter(
            FinancialPeriod.year_id == uuid.UUID(req.year_id),
            FinancialPeriod.tenant_id == tenant_id,
            FinancialPeriod.period_type == cc.period_granularity,
        ).order_by(FinancialPeriod.period_number).all()
        if periods:
            share = req.budget_minor // len(periods)
            remainder = req.budget_minor - share * len(periods)
            for idx, p in enumerate(periods):
                amount = share + (remainder if idx == len(periods) - 1 else 0)
                db.add(CostCentreBudgetVersion(
                    version_id=uuid.uuid4(),
                    cost_centre_id=cc.cost_centre_id,
                    year_id=uuid.UUID(req.year_id),
                    period_id=p.period_id,
                    tenant_id=tenant_id,
                    currency=req.currency,
                    budget_minor=amount,
                    status="active",
                    created_by=user_id,
                ))

    db.commit()
    db.refresh(version)

    _write_outbox(db, tenant_id, "cc_budget_version.created",
                  {"version_id": str(version.version_id), "cost_centre_id": req.cost_centre_id,
                   "budget_minor": req.budget_minor})

    return _version_dict(version)


@router.get("/cc-versions")
async def list_cc_budget_versions(
    cost_centre_id: Optional[str] = Query(None),
    year_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(CostCentreBudgetVersion).filter(CostCentreBudgetVersion.tenant_id == tenant_id)
    if cost_centre_id:
        q = q.filter(CostCentreBudgetVersion.cost_centre_id == uuid.UUID(cost_centre_id))
    if year_id:
        q = q.filter(CostCentreBudgetVersion.year_id == uuid.UUID(year_id))
    if status:
        q = q.filter(CostCentreBudgetVersion.status == status)
    total = q.count()
    rows  = q.order_by(CostCentreBudgetVersion.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "versions": [_version_dict(v) for v in rows]}


@router.get("/cc-versions/{version_id}")
async def get_cc_budget_version(
    version_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    v = _get_version_or_404(db, version_id, tenant_id)
    return _version_dict(v)


@router.put("/cc-versions/{version_id}")
async def update_cc_budget_version(
    version_id: str,
    req: CCBudgetVersionUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    policy_result: dict = Depends(require_policy("budget.update_version")),
):
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)
    v = _get_version_or_404(db, version_id, tenant_id)

    if req.budget_minor is not None:
        delta = req.budget_minor - v.budget_minor
        v.budget_minor = req.budget_minor
        if delta != 0:
            _record_txn(db, tenant_id, "top_up" if delta > 0 else "reallocation_debit",
                        None, v.version_id, abs(delta), v.currency, user_id,
                        req.override_reason or "Budget adjustment")
    if req.status is not None:
        v.status = req.status
        if req.status == "closed":
            v.closed_at = datetime.now(timezone.utc)
            v.closed_by = user_id
    if req.override_reason is not None:
        v.override_reason = req.override_reason

    v.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(v)

    _write_outbox(db, tenant_id, "cc_budget_version.updated",
                  {"version_id": version_id, "status": v.status})

    return _version_dict(v)


# =============================================================================
# REALLOCATION
# =============================================================================

@router.post("/reallocate", status_code=201)
async def reallocate_budget(
    req: BudgetReallocationRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    # OPA checks: source_available < amount → deny.
    policy_result: dict = Depends(
        require_policy("budget.reallocate", resource_loader=budget_reallocate_resource)
    ),
):
    """
    Transfer (or add) budget between two CC budget versions.
    source_version_id=null means additive top-up from central pool.
    OPA has already validated source headroom.
    """
    tenant_id = _tid(ctx)
    user_id   = _uid(ctx)

    target = _get_version_or_404(db, req.target_version_id, tenant_id)

    if req.source_version_id:
        source = _get_version_or_404(db, req.source_version_id, tenant_id)
        source.budget_minor -= req.amount_minor
        _record_txn(db, tenant_id, "reallocation_debit",
                    source.version_id, target.version_id,
                    req.amount_minor, target.currency, user_id, req.note)
    else:
        _record_txn(db, tenant_id, "top_up",
                    None, target.version_id,
                    req.amount_minor, target.currency, user_id, req.note)

    target.budget_minor += req.amount_minor
    _record_txn(db, tenant_id, "reallocation_credit",
                None, target.version_id,
                req.amount_minor, target.currency, user_id, req.note)

    db.commit()

    _write_outbox(db, tenant_id, "budget.reallocated",
                  {"target_version_id": req.target_version_id,
                   "amount_minor": req.amount_minor})

    return {"status": "ok", "target_version_id": req.target_version_id,
            "new_budget_minor": target.budget_minor}


# =============================================================================
# BUDGET DISTRIBUTION (per-period breakdown for a CC + financial year)
# =============================================================================

@router.get("/cc-distribution")
async def get_cc_distribution(
    cost_centre_id: str = Query(...),
    year_id: str = Query(...),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    """Per-period budget rows for the distribution table (month/quarter/year)."""
    tenant_id = _tid(ctx)
    cc = db.query(CostCentre).filter(
        CostCentre.cost_centre_id == uuid.UUID(cost_centre_id),
        CostCentre.tenant_id == tenant_id,
    ).first()
    if not cc:
        raise HTTPException(404, "Cost centre not found")

    annual = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == cc.cost_centre_id,
        CostCentreBudgetVersion.year_id == uuid.UUID(year_id),
        CostCentreBudgetVersion.period_id.is_(None),
        CostCentreBudgetVersion.status != "closed",
    ).first()

    period_versions = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == cc.cost_centre_id,
        CostCentreBudgetVersion.year_id == uuid.UUID(year_id),
        CostCentreBudgetVersion.period_id.isnot(None),
    ).all()
    period_ids = [v.period_id for v in period_versions]
    periods = {
        p.period_id: p
        for p in db.query(FinancialPeriod).filter(FinancialPeriod.period_id.in_(period_ids)).all()
    } if period_ids else {}

    rows = []
    for v in period_versions:
        p = periods.get(v.period_id)
        rows.append({
            "version_id": str(v.version_id),
            "period_id": str(v.period_id),
            "period_label": p.label if p else None,
            "period_number": p.period_number if p else None,
            "budget_minor": v.budget_minor,
            "used_minor": (v.spent_minor or 0) + (v.committed_minor or 0),
            "available_minor": v.budget_minor - (v.committed_minor or 0) - (v.spent_minor or 0),
            "status": v.status,
        })
    rows.sort(key=lambda r: r["period_number"] or 0)

    return {
        "cost_centre_id": cost_centre_id,
        "year_id": year_id,
        "mode": cc.period_granularity or "month",
        "annual_budget_minor": annual.budget_minor if annual else 0,
        "annual_version_id": str(annual.version_id) if annual else None,
        "distributed_minor": sum(r["budget_minor"] for r in rows),
        "periods": rows,
    }


@router.put("/cc-distribution")
async def set_cc_distribution(
    req: CCDistributionRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    policy_result: dict = Depends(require_policy("budget.update_version")),
):
    """Bulk-set per-period budgets. Total must equal the annual version budget."""
    tenant_id = _tid(ctx)
    user_id = _uid(ctx)

    if req.mode not in ("monthly", "quarterly", "yearly", "one_time"):
        raise HTTPException(400, "mode must be monthly | quarterly | yearly | one_time")

    cc = db.query(CostCentre).filter(
        CostCentre.cost_centre_id == uuid.UUID(req.cost_centre_id),
        CostCentre.tenant_id == tenant_id,
    ).first()
    if not cc:
        raise HTTPException(404, "Cost centre not found")

    annual = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == cc.cost_centre_id,
        CostCentreBudgetVersion.year_id == uuid.UUID(req.year_id),
        CostCentreBudgetVersion.period_id.is_(None),
        CostCentreBudgetVersion.status != "closed",
    ).first()
    if not annual:
        raise HTTPException(404, "No active annual budget version for this cost centre + year")

    total = sum(i.amount_minor for i in req.items)
    if total != annual.budget_minor:
        raise HTTPException(
            400,
            f"Distribution total ({total}) must equal annual budget ({annual.budget_minor})",
        )

    # Validate periods belong to the year
    period_ids = [uuid.UUID(i.period_id) for i in req.items if i.period_id]
    periods = {
        p.period_id: p
        for p in db.query(FinancialPeriod).filter(
            FinancialPeriod.period_id.in_(period_ids),
            FinancialPeriod.year_id == uuid.UUID(req.year_id),
        ).all()
    } if period_ids else {}
    missing = [str(pid) for pid in period_ids if pid not in periods]
    if missing:
        raise HTTPException(404, f"Period(s) not found in this year: {', '.join(missing)}")

    # Upsert period versions
    existing = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.cost_centre_id == cc.cost_centre_id,
        CostCentreBudgetVersion.year_id == uuid.UUID(req.year_id),
        CostCentreBudgetVersion.period_id.isnot(None),
    ).all()
    existing_by_period = {str(v.period_id): v for v in existing}

    for item in req.items:
        if not item.period_id:
            continue  # yearly/one_time: amount lives on the annual version
        v = existing_by_period.get(item.period_id)
        if v:
            v.budget_minor = item.amount_minor
            v.updated_at = datetime.now(timezone.utc)
        else:
            v = CostCentreBudgetVersion(
                version_id=uuid.uuid4(),
                cost_centre_id=cc.cost_centre_id,
                year_id=uuid.UUID(req.year_id),
                period_id=uuid.UUID(item.period_id),
                tenant_id=tenant_id,
                currency=annual.currency,
                budget_minor=item.amount_minor,
                status="active",
                created_by=user_id,
            )
            db.add(v)

    # Remove period rows no longer present
    keep = {i.period_id for i in req.items if i.period_id}
    for pid, v in existing_by_period.items():
        if pid not in keep:
            v.status = "closed"
            v.closed_at = datetime.now(timezone.utc)
            v.closed_by = user_id

    # Remember the CC's distribution pattern ("follows usual pattern" on Add year)
    cc.period_granularity = {"monthly": "month", "quarterly": "quarter",
                             "yearly": "year", "one_time": "year"}[req.mode]
    cc.updated_at = datetime.now(timezone.utc)

    db.add(CostCentreAuditEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, cost_centre_id=cc.cost_centre_id,
        actor_user_id=user_id, action="budget.updated",
        detail=f"Set {req.mode} distribution for year {req.year_id}: {len(req.items)} period(s), total {total}",
    ))
    db.commit()

    _write_outbox(db, tenant_id, "cc_budget_distribution.updated",
                  {"cost_centre_id": req.cost_centre_id, "year_id": req.year_id,
                   "mode": req.mode, "total_minor": total})

    return {"status": "ok", "cost_centre_id": req.cost_centre_id,
            "year_id": req.year_id, "mode": req.mode, "distributed_minor": total}


# =============================================================================
# END OF FINANCIAL YEAR — carry forward or expire remaining budget
# =============================================================================

@router.post("/cc-versions/{version_id}/carry-forward", status_code=200)
async def carry_forward_cc_version(
    version_id: str,
    req: CarryForwardRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
    policy_result: dict = Depends(require_policy("budget.update_version")),
):
    """
    End-of-FY decision on an annual version:
    - carry_forward: close this year, add remaining to next year's version
    - expire: close this year, remaining lapses
    """
    tenant_id = _tid(ctx)
    user_id = _uid(ctx)
    v = _get_version_or_404(db, version_id, tenant_id)

    if v.status == "closed":
        raise HTTPException(400, "Budget version already closed")
    if req.action not in ("carry_forward", "expire"):
        raise HTTPException(400, "action must be carry_forward | expire")

    remaining = v.budget_minor + (v.carry_forward_minor or 0) \
        - (v.committed_minor or 0) - (v.spent_minor or 0)
    if remaining < 0:
        remaining = 0

    target_version = None
    if req.action == "carry_forward":
        if not req.target_year_id:
            raise HTTPException(400, "target_year_id required for carry_forward")
        year = db.query(FinancialYear).filter(
            FinancialYear.year_id == uuid.UUID(req.target_year_id),
            FinancialYear.tenant_id == tenant_id,
        ).first()
        if not year:
            raise HTTPException(404, "Target financial year not found")

        target_version = db.query(CostCentreBudgetVersion).filter(
            CostCentreBudgetVersion.cost_centre_id == v.cost_centre_id,
            CostCentreBudgetVersion.year_id == uuid.UUID(req.target_year_id),
            CostCentreBudgetVersion.period_id.is_(None),
            CostCentreBudgetVersion.status != "closed",
        ).first()
        if not target_version:
            target_version = CostCentreBudgetVersion(
                version_id=uuid.uuid4(),
                cost_centre_id=v.cost_centre_id,
                year_id=uuid.UUID(req.target_year_id),
                period_id=None,
                tenant_id=tenant_id,
                currency=v.currency,
                budget_minor=0,
                carry_forward_minor=0,
                status="active",
                created_by=user_id,
            )
            db.add(target_version)
            db.flush()
        target_version.carry_forward_minor = (target_version.carry_forward_minor or 0) + remaining
        _record_txn(db, tenant_id, "carry_forward", v.version_id, target_version.version_id,
                    remaining, v.currency, user_id, "End-of-year carry forward")

    # Close the source year
    v.status = "closed"
    v.closed_at = datetime.now(timezone.utc)
    v.closed_by = user_id
    v.updated_at = datetime.now(timezone.utc)

    db.add(CostCentreAuditEvent(
        id=uuid.uuid4(), tenant_id=tenant_id, cost_centre_id=v.cost_centre_id,
        actor_user_id=user_id, action="budget.updated",
        detail=(f"Closed year budget: carried forward {remaining}"
                if req.action == "carry_forward" else
                f"Closed year budget: {remaining} expired"),
    ))
    db.commit()

    _write_outbox(db, tenant_id, "cc_budget_version.carry_forward",
                  {"version_id": version_id, "action": req.action, "remaining_minor": remaining})

    return {
        "status": "ok",
        "action": req.action,
        "remaining_minor": remaining,
        "target_version_id": str(target_version.version_id) if target_version else None,
    }


# =============================================================================
# BUDGET TRANSACTIONS (read-only ledger)
# =============================================================================
@router.get("/transactions")
async def list_budget_transactions(
    version_id: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    txn_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
):
    tenant_id = _tid(ctx)
    q = db.query(BudgetTransaction).filter(BudgetTransaction.tenant_id == tenant_id)
    if version_id:
        vid = uuid.UUID(version_id)
        q = q.filter(
            (BudgetTransaction.source_version_id == vid) |
            (BudgetTransaction.target_version_id == vid)
        )
    if txn_type:
        q = q.filter(BudgetTransaction.txn_type == txn_type)
    total = q.count()
    rows  = q.order_by(BudgetTransaction.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "transactions": [
            {
                "txn_id":            str(t.txn_id),
                "txn_type":          t.txn_type,
                "source_version_id": str(t.source_version_id) if t.source_version_id else None,
                "target_version_id": str(t.target_version_id) if t.target_version_id else None,
                "amount_minor":      t.amount_minor,
                "currency":          t.currency,
                "note":              t.note,
                "performed_by":      str(t.performed_by) if t.performed_by else None,
                "created_at":        t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ],
    }


# =============================================================================
# Internal helpers
# =============================================================================

def _tid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))


def _uid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))


def _get_cap_or_404(db, cap_id, tenant_id):
    try:
        cid = uuid.UUID(cap_id)
    except ValueError:
        raise HTTPException(400, "Invalid cap_id")
    cap = db.query(CompanyBudgetCap).filter(
        CompanyBudgetCap.cap_id == cid, CompanyBudgetCap.tenant_id == tenant_id
    ).first()
    if not cap:
        raise HTTPException(404, "Company budget cap not found")
    return cap


def _get_version_or_404(db, version_id, tenant_id):
    try:
        vid = uuid.UUID(version_id)
    except ValueError:
        raise HTTPException(400, "Invalid version_id")
    v = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.version_id == vid,
        CostCentreBudgetVersion.tenant_id == tenant_id,
    ).first()
    if not v:
        raise HTTPException(404, "CC budget version not found")
    return v


def _record_txn(db, tenant_id, txn_type, source_id, target_id, amount, currency, user_id, note):
    db.add(BudgetTransaction(
        txn_id=uuid.uuid4(),
        tenant_id=tenant_id,
        txn_type=txn_type,
        source_version_id=source_id,
        target_version_id=target_id,
        amount_minor=amount,
        currency=currency,
        performed_by=user_id,
        note=note,
    ))


def _write_outbox(db, tenant_id, event_type, data):
    try:
        create_outbox_event(db, tenant_id, event_type, data)
        db.commit()
    except Exception as e:
        logger.warning(f"Outbox failed for {event_type}: {e}")


def _cap_dict(cap):
    return {
        "cap_id":              str(cap.cap_id),
        "tenant_id":           str(cap.tenant_id),
        "year_id":             str(cap.year_id),
        "currency":            cap.currency,
        "total_budget_minor":  cap.total_budget_minor,
        "allocated_minor":     cap.allocated_minor,
        "committed_minor":     cap.committed_minor,
        "spent_minor":         cap.spent_minor,
        "hard_cap":            cap.hard_cap,
        "available_minor": cap.total_budget_minor - (cap.committed_minor or 0) - (cap.spent_minor or 0),
    }


def _version_dict(v):
    available = (
        v.budget_minor
        + (v.carry_forward_minor or 0)
        - (v.committed_minor or 0)
        - (v.spent_minor or 0)
    )
    return {
        "version_id":               str(v.version_id),
        "cost_centre_id":           str(v.cost_centre_id),
        "year_id":                  str(v.year_id),
        "period_id":                str(v.period_id) if v.period_id else None,
        "currency":                 v.currency,
        "budget_minor":             v.budget_minor,
        "carry_forward_minor":      v.carry_forward_minor or 0,
        "allocated_to_users_minor": v.allocated_to_users_minor or 0,
        "committed_minor":          v.committed_minor or 0,
        "spent_minor":              v.spent_minor or 0,
        "available_minor":          available,
        "status":                   v.status,
        "override_reason":          v.override_reason,
    }
