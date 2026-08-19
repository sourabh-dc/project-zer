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

from fastapi import Depends, HTTPException, Request
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
# budget.create_version  — company cap headroom check
# ---------------------------------------------------------------------------

async def cc_budget_create_resource(
    request: Request,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
) -> Dict[str, Any]:
    """OPA resource context for budget.create_version."""
    from provisioning_service.Models import CompanyBudgetCap

    try:
        body = await request.json()
    except Exception:
        body = {}

    tenant_id     = _tid(ctx)
    year_id_str   = body.get("year_id", "")
    budget_minor  = body.get("budget_minor", 0)
    override_reason = body.get("override_reason") or ""

    try:
        year_uuid = uuid.UUID(year_id_str)
    except (ValueError, AttributeError):
        return {
            "tenant_id":              str(tenant_id),
            "budget_minor":           budget_minor,
            "cap_total_budget_minor": None,
            "cap_allocated_minor":    None,
            "hard_cap":               False,
            "would_exceed_cap":       False,
            "override_reason":        override_reason,
        }

    cap: Optional[CompanyBudgetCap] = db.query(CompanyBudgetCap).filter(
        CompanyBudgetCap.tenant_id == tenant_id,
        CompanyBudgetCap.year_id == year_uuid,
    ).first()

    if not cap:
        return {
            "tenant_id":              str(tenant_id),
            "budget_minor":           budget_minor,
            "cap_total_budget_minor": None,
            "cap_allocated_minor":    None,
            "hard_cap":               False,
            "would_exceed_cap":       False,
            "override_reason":        override_reason,
        }

    current_allocated = cap.allocated_minor or 0
    new_allocated = current_allocated + budget_minor
    would_exceed = new_allocated > cap.total_budget_minor

    return {
        "tenant_id":              str(tenant_id),
        "budget_minor":           budget_minor,
        "cap_total_budget_minor": cap.total_budget_minor,
        "cap_allocated_minor":    current_allocated,
        "new_allocated":          new_allocated,
        "hard_cap":               cap.hard_cap,
        "would_exceed_cap":       would_exceed,
        "override_reason":        override_reason,
    }


# ---------------------------------------------------------------------------
# budget.update_cap  — check new total vs already-allocated
# ---------------------------------------------------------------------------

async def company_cap_update_resource(
    cap_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
) -> Dict[str, Any]:
    """OPA resource context for budget.update_cap."""
    from provisioning_service.Models import CompanyBudgetCap, CostCentreBudgetVersion

    try:
        body = await request.json()
    except Exception:
        body = {}

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

    total_budget_minor = body.get("total_budget_minor")
    override_reason    = body.get("override_reason") or ""
    new_total = total_budget_minor if total_budget_minor is not None else cap.total_budget_minor

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
    would_underfund = (total_budget_minor is not None) and (allocated_sum > new_total)

    return {
        "tenant_id":              str(tenant_id),
        "new_total_budget_minor": new_total,
        "current_allocated":      allocated_sum,
        "hard_cap":               cap.hard_cap,
        "would_underfund":        would_underfund,
        "override_reason":        override_reason,
    }


# ---------------------------------------------------------------------------
# budget.reallocate  — source version headroom
# ---------------------------------------------------------------------------

async def budget_reallocate_resource(
    request: Request,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.manage")),
) -> Dict[str, Any]:
    """OPA resource context for budget.reallocate."""
    from provisioning_service.Models import CostCentreBudgetVersion

    try:
        body = await request.json()
    except Exception:
        body = {}

    tenant_id          = _tid(ctx)
    source_version_id  = body.get("source_version_id")
    amount_minor       = body.get("amount_minor", 0)
    target_version_id  = body.get("target_version_id")
    source_available: Optional[int] = None

    if source_version_id:
        try:
            src_id = uuid.UUID(source_version_id)
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
        "amount_minor":          amount_minor,
        "source_version_id":     source_version_id,
        "source_available_minor": source_available,
        "target_version_id":     target_version_id,
    }


# ---------------------------------------------------------------------------
# budget_change.bring_forward  — future period headroom
# ---------------------------------------------------------------------------

async def bring_forward_resource(
    request: Request,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budget.request")),
) -> Dict[str, Any]:
    """OPA resource context for budget_change.bring_forward."""
    from provisioning_service.Models import CostCentreBudgetVersion

    try:
        body = await request.json()
    except Exception:
        body = {}

    tenant_id       = _tid(ctx)
    from_version_id = body.get("from_version_id", "")
    to_version_id   = body.get("to_version_id")
    amount_minor    = body.get("amount_minor", 0)

    try:
        from_vid = uuid.UUID(from_version_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid from_version_id")

    from_v = db.query(CostCentreBudgetVersion).filter(
        CostCentreBudgetVersion.version_id == from_vid,
        CostCentreBudgetVersion.tenant_id == tenant_id,
    ).first()
    if not from_v:
        raise HTTPException(404, "Source budget version not found")

    from_available = from_v.budget_minor - (from_v.committed_minor or 0) - (from_v.spent_minor or 0)

    return {
        "tenant_id":            str(tenant_id),
        "amount_minor":         amount_minor,
        "from_available_minor": from_available,
        "from_version_id":      from_version_id,
        "to_version_id":        to_version_id,
    }


# ---------------------------------------------------------------------------
# Entitlement / quota loader factory  (sites, stores, users, vendors, cost centres)
# ---------------------------------------------------------------------------

def entitlement_resource_loader(feature_code: str, *, first_free: bool = False):
    """
    Factory: returns a FastAPI dependency that loads subscription quota context
    for OPA provisioning entitlement checks.

    Usage::

        resource_loader = entitlement_resource_loader("supplier.records")
        require_policy("vendor.create", resource_loader=resource_loader)

    Parses ``tenant_id`` from the raw request body JSON so that no untyped
    ``req`` parameter leaks into FastAPI's DI graph as a phantom query param.

    ``first_free``: when True, the first resource of this type is always
    allowed (e.g. a baseline site/location), and the plan feature gates only
    the *second* resource onwards. This models ``multi.site`` / ``multi.location``
    boolean upsell features that don't carry a numeric quota.
    """

    async def _loader(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
        try:
            body = await request.json()
            tenant_id_str = str(body.get("tenant_id", ""))
        except Exception:
            tenant_id_str = ""

        active, _plan_code, _plan_name, features = load_tenant_features(db, tenant_id_str)
        feature = features.get(feature_code)
        current_count = feature.used if feature else 0

        feature_in_plan = feature_code in features
        feature_limit = feature.limit if feature else 0

        if first_free and current_count == 0:
            # Baseline resource is always permitted; the feature gates extras.
            feature_in_plan = True
            feature_limit = None

        return {
            "tenant_id":           tenant_id_str,
            "subscription_active": active,
            "feature_code":        feature_code,
            "feature_in_plan":     feature_in_plan,
            "current_count":       current_count,
            "feature_limit":       feature_limit,
        }

    # Give each loader a unique __name__ so FastAPI's DI system treats
    # different feature codes as distinct dependencies.
    _loader.__name__ = f"entitlement_resource_loader_{feature_code.replace('.', '_')}"
    return _loader


# ---------------------------------------------------------------------------
# Pre-built entitlement loaders (imported directly by route files)
#
# Feature codes MUST match the seeded plan features in
# `provisioning_service/core/helpers/load_plans.py`:
#   - active.users      (numeric seat quota: 5/15/40/100)
#   - supplier.records  (numeric supplier quota: 10/25/100/500)
#   - cost.centres      (numeric cost-centre quota: 2/10/50/200)
#   - multi.site        (boolean — enables adding more sites)
#   - multi.location    (boolean — enables adding more stores/locations)
# ---------------------------------------------------------------------------

site_quota_resource        = entitlement_resource_loader("multi.site", first_free=True)
store_quota_resource       = entitlement_resource_loader("multi.location", first_free=True)
user_quota_resource        = entitlement_resource_loader("active.users")
vendor_quota_resource      = entitlement_resource_loader("supplier.records")
cost_centre_quota_resource = entitlement_resource_loader("cost.centres")
