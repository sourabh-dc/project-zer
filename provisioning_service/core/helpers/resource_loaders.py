"""
resource_loaders.py
--------------------
FastAPI dependency functions that query the DB and return enriched resource
context dicts for OPA policy evaluation.

Each loader is passed as ``resource_loader=`` to ``require_policy()``.
FastAPI's DI system caches dependency results per-request, so a loader
declared both in the route signature and inside ``require_policy`` is
executed only once — no duplicate DB round-trips.

Naming convention: <domain>_<action>_resource
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from provisioning_service.core.db_config import get_db
from provisioning_service.core.entitlement_helpers import load_tenant_features
from provisioning_service.core.period_calculator import get_current_period
from provisioning_service.core.user_auth import check_user_authorization


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["tenant_id"] if isinstance(ctx, dict) else str(ctx.tenant_id))


def _uid(ctx) -> uuid.UUID:
    return uuid.UUID(ctx["user_id"] if isinstance(ctx, dict) else str(ctx.user_id))


# ---------------------------------------------------------------------------
# purchase_request.create
# ---------------------------------------------------------------------------

def purchase_request_create_resource(req, db: Session = Depends(get_db),
                                     ctx=Depends(check_user_authorization("orders.place"))) -> Dict[str, Any]:
    """
    Computes budget headroom and returns OPA resource context for
    purchase_request.create.  Used by both require_policy and the route body.
    """
    from provisioning_service.core.budget_engine import check_request_headroom

    tenant_id    = _tid(ctx)
    requester_id = _uid(ctx)

    current_period = get_current_period(db, tenant_id)
    year_id   = current_period.year_id   if current_period else None
    period_id = current_period.period_id if current_period else None

    budget_check = check_request_headroom(
        db,
        tenant_id=tenant_id,
        requester_id=requester_id,
        cost_centre_id=uuid.UUID(req.cost_centre_id),
        amount_minor=req.amount_minor,
        year_id=year_id,
        period_id=period_id,
    )

    return {
        "tenant_id":                  str(tenant_id),
        "amount_minor":               req.amount_minor,
        "cost_centre_id":             req.cost_centre_id,
        "vendor_id":                  req.vendor_id,
        "category_id":                getattr(req, "category_id", None),
        "cc_headroom_minor":          budget_check.cc_headroom_minor,
        "company_cap_headroom_minor": budget_check.company_cap_headroom_minor,
        "is_blocked":                 budget_check.is_blocked,
        "block_reason":               budget_check.block_reason or "",
        "can_self_approve":           budget_check.can_self_approve,
        "needs_approval":             budget_check.needs_approval,
    }


# ---------------------------------------------------------------------------
# purchase_request.decide
# ---------------------------------------------------------------------------

def purchase_request_decide_resource(
    task_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("orders.approve")),
) -> Dict[str, Any]:
    """
    Loads the approval task → workflow → purchase request → policy chain
    and returns OPA resource context for purchase_request.decide.
    """
    from provisioning_service.Models import (
        ApprovalTask, ApprovalWorkflow, PurchaseRequest, ApprovalPolicy,
    )

    tenant_id = _tid(ctx)

    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(400, "Invalid task_id")

    task = db.query(ApprovalTask).filter(
        ApprovalTask.task_id == tid,
        ApprovalTask.tenant_id == tenant_id,
    ).first()
    if not task:
        raise HTTPException(404, "Approval task not found")

    workflow = db.query(ApprovalWorkflow).filter(
        ApprovalWorkflow.workflow_id == task.workflow_id
    ).first()

    pr = (
        db.query(PurchaseRequest).filter(
            PurchaseRequest.request_id == workflow.request_id
        ).first()
        if workflow else None
    )

    policy = (
        db.query(ApprovalPolicy).filter(
            ApprovalPolicy.policy_id == workflow.policy_id
        ).first()
        if workflow else None
    )

    return {
        "tenant_id":       str(tenant_id),
        "task_id":         str(tid),
        "requester_id":    str(pr.requester_id) if pr else "",
        "sox_sod_enforced": policy.sox_sod_enforced if policy else True,
    }


# ---------------------------------------------------------------------------
# budget.create_version  — company cap headroom check
# ---------------------------------------------------------------------------

def cc_budget_create_resource(req, db: Session = Depends(get_db),
                               ctx=Depends(check_user_authorization("budget.manage"))) -> Dict[str, Any]:
    """OPA resource context for budget.create_version."""
    from provisioning_service.Models import CompanyBudgetCap

    tenant_id = _tid(ctx)

    cap: Optional[CompanyBudgetCap] = db.query(CompanyBudgetCap).filter(
        CompanyBudgetCap.tenant_id == tenant_id,
        CompanyBudgetCap.year_id == uuid.UUID(req.year_id),
    ).first()

    if not cap:
        return {
            "tenant_id":              str(tenant_id),
            "budget_minor":           req.budget_minor,
            "cap_total_budget_minor": None,
            "cap_allocated_minor":    None,
            "hard_cap":               False,
            "would_exceed_cap":       False,
            "override_reason":        req.override_reason or "",
        }

    current_allocated = cap.allocated_minor or 0
    new_allocated = current_allocated + req.budget_minor
    would_exceed = new_allocated > cap.total_budget_minor

    return {
        "tenant_id":              str(tenant_id),
        "budget_minor":           req.budget_minor,
        "cap_total_budget_minor": cap.total_budget_minor,
        "cap_allocated_minor":    current_allocated,
        "new_allocated":          new_allocated,
        "hard_cap":               cap.hard_cap,
        "would_exceed_cap":       would_exceed,
        "override_reason":        req.override_reason or "",
    }


# ---------------------------------------------------------------------------
# budget.update_cap  — check new total vs already-allocated
# ---------------------------------------------------------------------------

def company_cap_update_resource(
    cap_id: str,
    req,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
) -> Dict[str, Any]:
    """OPA resource context for budget.update_cap."""
    from provisioning_service.Models import CompanyBudgetCap, CostCentreBudgetVersion

    tenant_id = _tid(ctx)

    try:
        cid = uuid.UUID(cap_id)
    except ValueError:
        raise HTTPException(400, "Invalid cap_id")

    cap = db.query(CompanyBudgetCap).filter(
        CompanyBudgetCap.cap_id == cid,
        CompanyBudgetCap.tenant_id == tenant_id,
    ).first()
    if not cap:
        raise HTTPException(404, "Company budget cap not found")

    new_total = req.total_budget_minor if req.total_budget_minor is not None else cap.total_budget_minor

    # Sum of all active CC budget versions for this year
    rows = (
        db.query(CostCentreBudgetVersion)
        .filter(
            CostCentreBudgetVersion.year_id == cap.year_id,
            CostCentreBudgetVersion.tenant_id == tenant_id,
            CostCentreBudgetVersion.status == "active",
        )
        .with_entities(CostCentreBudgetVersion.budget_minor)
        .all()
    )
    allocated_sum = sum(r[0] for r in rows)
    would_underfund = (req.total_budget_minor is not None) and (allocated_sum > new_total)

    return {
        "tenant_id":              str(tenant_id),
        "new_total_budget_minor": new_total,
        "current_allocated":      allocated_sum,
        "hard_cap":               cap.hard_cap,
        "would_underfund":        would_underfund,
        "override_reason":        getattr(req, "override_reason", None) or "",
    }


# ---------------------------------------------------------------------------
# budget.reallocate  — source version headroom
# ---------------------------------------------------------------------------

def budget_reallocate_resource(req, db: Session = Depends(get_db),
                                ctx=Depends(check_user_authorization("budget.manage"))) -> Dict[str, Any]:
    """OPA resource context for budget.reallocate."""
    from provisioning_service.Models import CostCentreBudgetVersion

    tenant_id = _tid(ctx)
    source_available: Optional[int] = None

    if req.source_version_id:
        try:
            src_id = uuid.UUID(req.source_version_id)
        except ValueError:
            raise HTTPException(400, "Invalid source_version_id")
        src = db.query(CostCentreBudgetVersion).filter(
            CostCentreBudgetVersion.version_id == src_id,
            CostCentreBudgetVersion.tenant_id == tenant_id,
        ).first()
        if not src:
            raise HTTPException(404, "Source budget version not found")
        source_available = src.budget_minor - (src.committed_minor or 0) - (src.spent_minor or 0)

    return {
        "tenant_id":             str(tenant_id),
        "amount_minor":          req.amount_minor,
        "source_version_id":     req.source_version_id,
        "source_available_minor": source_available,
        "target_version_id":     req.target_version_id,
    }


# ---------------------------------------------------------------------------
# budget_change.bring_forward  — future period headroom
# ---------------------------------------------------------------------------

def bring_forward_resource(req, db: Session = Depends(get_db),
                            ctx=Depends(check_user_authorization("budget.request"))) -> Dict[str, Any]:
    """OPA resource context for budget_change.bring_forward."""
    from provisioning_service.Models import CostCentreBudgetVersion

    tenant_id = _tid(ctx)

    try:
        from_vid = uuid.UUID(req.from_version_id)
    except ValueError:
        raise HTTPException(400, "Invalid from_version_id")

    from_v = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.version_id == from_vid,
        CostCentreBudgetVersion.tenant_id == tenant_id,
    ).first()
    if not from_v:
        raise HTTPException(404, "Source budget version not found")

    from_available = from_v.budget_minor - (from_v.committed_minor or 0) - (from_v.spent_minor or 0)

    return {
        "tenant_id":          str(tenant_id),
        "amount_minor":       req.amount_minor,
        "from_available_minor": from_available,
        "from_version_id":    req.from_version_id,
        "to_version_id":      req.to_version_id,
    }


# ---------------------------------------------------------------------------
# Entitlement / quota loader factory  (sites, stores, users, vendors, cost centres)
# ---------------------------------------------------------------------------

def entitlement_resource_loader(feature_code: str):
    """
    Factory: returns a FastAPI dependency that loads subscription quota context
    for OPA provisioning entitlement checks.

    Usage::

        resource_loader = entitlement_resource_loader("sites.manage")
        require_policy("site.create", resource_loader=resource_loader)

    The returned dependency declares ``req`` (the route's request body, which
    must have a ``tenant_id`` attribute) and ``db``.  FastAPI's DI cache
    ensures the body is only parsed once per request.
    """

    def _loader(req, db: Session = Depends(get_db)) -> Dict[str, Any]:
        tenant_id_str = str(req.tenant_id)
        active, _plan_code, _plan_name, features = load_tenant_features(db, tenant_id_str)
        feature = features.get(feature_code)

        return {
            "tenant_id":          tenant_id_str,
            "subscription_active": active,
            "feature_code":       feature_code,
            "feature_in_plan":    feature_code in features,
            "current_count":      feature.used      if feature else 0,
            "feature_limit":      feature.limit     if feature else 0,
        }

    # Give each loader a unique __name__ so FastAPI's DI system treats
    # different feature codes as distinct dependencies.
    _loader.__name__ = f"entitlement_resource_loader_{feature_code.replace('.', '_')}"
    return _loader


# ---------------------------------------------------------------------------
# Pre-built entitlement loaders (imported directly by route files)
# ---------------------------------------------------------------------------

site_quota_resource        = entitlement_resource_loader("sites.manage")
store_quota_resource       = entitlement_resource_loader("stores.manage")
user_quota_resource        = entitlement_resource_loader("users.manage")
vendor_quota_resource      = entitlement_resource_loader("vendors.manage")
cost_centre_quota_resource = entitlement_resource_loader("cost_centres")
