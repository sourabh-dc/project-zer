"""
Sub-Tenant & Advanced Access API — Phase 6

Sub-tenant hierarchy (Distributor Platform) and per-responsibility
scope overrides (Advanced Access).
"""
from __future__ import annotations

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Tenant, User, UserResponsibilityScope, SiteTenant, Store, Vendor,
    CostCentre, PurchaseRequest, TenantSubscription,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.entitlement_helpers import load_tenant_features
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(tags=["advanced-access"])

# ═══════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════

class SubTenantItem(BaseModel):
    tenant_id: str
    tenant_name: str
    tenant_type: str
    active: bool


class SubTenantListResponse(BaseModel):
    sub_tenants: List[SubTenantItem] = Field(default_factory=list)


class SubTenantCreate(BaseModel):
    tenant_name: str
    tenant_type: str = "retailer"   # retailer/brand/franchisee
    email: str


class SubTenantUpdate(BaseModel):
    tenant_name: Optional[str] = None
    tenant_type: Optional[str] = None
    active: Optional[bool] = None


class SubTenantDetail(SubTenantItem):
    email: Optional[str] = None
    parent_tenant_id: Optional[str] = None
    created_at: Optional[str] = None


class TenantHierarchyResponse(BaseModel):
    tenant: SubTenantItem
    parent: Optional[SubTenantItem] = None
    children: List[SubTenantItem] = Field(default_factory=list)


class CrossTenantAnalyticsItem(BaseModel):
    tenant_id: str
    tenant_name: str
    active: bool
    plan_code: Optional[str] = None
    subscription_status: Optional[str] = None
    active_users: int = 0
    sites: int = 0
    stores: int = 0
    vendors: int = 0
    cost_centres: int = 0
    purchase_requests: int = 0
    requested_amount_minor: int = 0
    currency: str = "GBP"


class CrossTenantAnalyticsResponse(BaseModel):
    parent_tenant_id: str
    sub_tenants: List[CrossTenantAnalyticsItem] = Field(default_factory=list)
    totals: CrossTenantAnalyticsItem


class ResponsibilityScopeCreate(BaseModel):
    user_id: str
    responsibility_code: str    # e.g. "approvals.requests.respond"
    scope_type: str             # site | cost_centre | department
    scope_id: str               # UUID of the scope target


class ResponsibilityScopeResponse(BaseModel):
    id: str
    user_id: str
    responsibility_code: str
    scope_type: str
    scope_id: str


class ResponsibilityScopeListResponse(BaseModel):
    scopes: List[ResponsibilityScopeResponse] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# Sub-Tenant endpoints
# ═══════════════════════════════════════════════════════════════════

@router.get("/tenants/{tenant_id}/sub-tenants", response_model=SubTenantListResponse)
async def list_sub_tenants(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """List all sub-tenants (child tenants) of a parent tenant."""
    # sub-tenants have parent_tenant_id matching the given tenant
    subs = db.query(Tenant).filter(
        Tenant.parent_tenant_id == tenant_id,
        Tenant.active == True,
    ).all()

    return SubTenantListResponse(sub_tenants=[
        SubTenantItem(
            tenant_id=str(t.tenant_id),
            tenant_name=t.tenant_name,
            tenant_type=t.tenant_type,
            active=t.active if t.active is not None else True,
        )
        for t in subs
    ])


# ── C1: sub-tenant CRUD + hierarchy ───────────────────────────────

def _require_plan_feature(db: Session, tenant_id: str, feature_code: str) -> None:
    """403 unless the tenant's active plan (or packs) include the feature."""
    active, _plan, _name, features = load_tenant_features(db, tenant_id)
    if not active:
        raise HTTPException(status_code=403, detail="No active subscription")
    if feature_code not in features:
        raise HTTPException(
            status_code=403,
            detail=f"Feature '{feature_code}' is not available on your plan",
        )


def _get_sub_tenant(db: Session, parent_id: str, sub_id: str) -> Tenant:
    sub = db.query(Tenant).filter(
        Tenant.tenant_id == sub_id,
        Tenant.parent_tenant_id == parent_id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sub-tenant not found")
    return sub


def _sub_item(t: Tenant) -> SubTenantItem:
    return SubTenantItem(
        tenant_id=str(t.tenant_id),
        tenant_name=t.tenant_name,
        tenant_type=t.tenant_type,
        active=t.active if t.active is not None else True,
    )


@router.post("/tenants/{tenant_id}/sub-tenants", response_model=SubTenantDetail, status_code=201)
async def create_sub_tenant(
    tenant_id: str,
    req: SubTenantCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """Create a sub-tenant under a distributor parent tenant."""
    parent = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent tenant not found")
    if parent.parent_tenant_id is not None:
        raise HTTPException(status_code=400, detail="Hierarchy depth exceeded: sub-tenants cannot have sub-tenants")

    _require_plan_feature(db, tenant_id, "multi.tenant.management")

    sub = Tenant(
        tenant_id=uuid.uuid4(),
        tenant_name=req.tenant_name,
        tenant_type=req.tenant_type,
        email=req.email,
        active=True,
        parent_tenant_id=parent.tenant_id,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    logger.info(f"Sub-tenant created: {sub.tenant_id} under parent {tenant_id}")
    return SubTenantDetail(
        **_sub_item(sub).model_dump(),
        email=sub.email,
        parent_tenant_id=str(sub.parent_tenant_id),
        created_at=sub.created_at.isoformat() if sub.created_at else None,
    )


@router.get("/tenants/{tenant_id}/sub-tenants/{sub_id}", response_model=SubTenantDetail)
async def get_sub_tenant(
    tenant_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """Fetch a single sub-tenant of the parent tenant."""
    sub = _get_sub_tenant(db, tenant_id, sub_id)
    return SubTenantDetail(
        **_sub_item(sub).model_dump(),
        email=sub.email,
        parent_tenant_id=str(sub.parent_tenant_id) if sub.parent_tenant_id else None,
        created_at=sub.created_at.isoformat() if sub.created_at else None,
    )


@router.patch("/tenants/{tenant_id}/sub-tenants/{sub_id}", response_model=SubTenantDetail)
async def update_sub_tenant(
    tenant_id: str,
    sub_id: str,
    req: SubTenantUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """Update a sub-tenant's name, type, or active flag."""
    sub = _get_sub_tenant(db, tenant_id, sub_id)
    if req.tenant_name is not None:
        sub.tenant_name = req.tenant_name
    if req.tenant_type is not None:
        sub.tenant_type = req.tenant_type
    if req.active is not None:
        sub.active = req.active
    db.commit()
    db.refresh(sub)
    logger.info(f"Sub-tenant updated: {sub_id} under parent {tenant_id}")
    return SubTenantDetail(
        **_sub_item(sub).model_dump(),
        email=sub.email,
        parent_tenant_id=str(sub.parent_tenant_id) if sub.parent_tenant_id else None,
        created_at=sub.created_at.isoformat() if sub.created_at else None,
    )


@router.delete("/tenants/{tenant_id}/sub-tenants/{sub_id}", status_code=204)
async def deactivate_sub_tenant(
    tenant_id: str,
    sub_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """Soft-delete: deactivate a sub-tenant (data retained)."""
    sub = _get_sub_tenant(db, tenant_id, sub_id)
    sub.active = False
    db.commit()
    logger.info(f"Sub-tenant deactivated: {sub_id} under parent {tenant_id}")


@router.get("/tenants/{tenant_id}/hierarchy", response_model=TenantHierarchyResponse)
async def get_tenant_hierarchy(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """Return the tenant with its parent (if any) and direct children."""
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    parent = None
    if tenant.parent_tenant_id:
        p = db.query(Tenant).filter(Tenant.tenant_id == tenant.parent_tenant_id).first()
        if p:
            parent = _sub_item(p)

    children = db.query(Tenant).filter(
        Tenant.parent_tenant_id == tenant.tenant_id,
        Tenant.active == True,
    ).all()

    return TenantHierarchyResponse(
        tenant=_sub_item(tenant),
        parent=parent,
        children=[_sub_item(c) for c in children],
    )


# ── C2: cross-tenant analytics ────────────────────────────────────

def _tenant_analytics(db: Session, t: Tenant) -> CrossTenantAnalyticsItem:
    tid = t.tenant_id
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tid,
        TenantSubscription.is_active == True,
    ).first()
    pr_count, pr_amount = db.query(
        func.count(PurchaseRequest.request_id),
        func.coalesce(func.sum(PurchaseRequest.amount_minor), 0),
    ).filter(PurchaseRequest.tenant_id == tid).first()

    return CrossTenantAnalyticsItem(
        tenant_id=str(tid),
        tenant_name=t.tenant_name,
        active=t.active if t.active is not None else True,
        plan_code=sub.plan_code if sub else None,
        subscription_status=sub.status if sub else None,
        active_users=db.query(User).filter(User.tenant_id == tid, User.is_active == True).count(),
        sites=db.query(SiteTenant).filter(SiteTenant.tenant_id == tid).count(),
        stores=db.query(Store).filter(Store.tenant_id == tid, Store.active == True).count(),
        vendors=db.query(Vendor).filter(Vendor.tenant_id == tid, Vendor.status == "active").count(),
        cost_centres=db.query(CostCentre).filter(CostCentre.tenant_id == tid).count(),
        purchase_requests=pr_count or 0,
        requested_amount_minor=int(pr_amount or 0),
    )


@router.get("/tenants/{tenant_id}/analytics/cross-tenant", response_model=CrossTenantAnalyticsResponse)
async def cross_tenant_analytics(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
):
    """Aggregate usage analytics across all sub-tenants (Distributor Platform)."""
    _require_plan_feature(db, tenant_id, "cross.tenant.analytics")

    subs = db.query(Tenant).filter(Tenant.parent_tenant_id == tenant_id).all()
    items = [_tenant_analytics(db, t) for t in subs]

    totals = CrossTenantAnalyticsItem(
        tenant_id=str(tenant_id),
        tenant_name="(totals)",
        active=True,
        active_users=sum(i.active_users for i in items),
        sites=sum(i.sites for i in items),
        stores=sum(i.stores for i in items),
        vendors=sum(i.vendors for i in items),
        cost_centres=sum(i.cost_centres for i in items),
        purchase_requests=sum(i.purchase_requests for i in items),
        requested_amount_minor=sum(i.requested_amount_minor for i in items),
    )
    return CrossTenantAnalyticsResponse(
        parent_tenant_id=str(tenant_id),
        sub_tenants=items,
        totals=totals,
    )


# ═══════════════════════════════════════════════════════════════════
# Advanced Access: per-responsibility scope overrides
# ═══════════════════════════════════════════════════════════════════

@router.get("/user-responsibility-scopes", response_model=ResponsibilityScopeListResponse)
async def list_user_responsibility_scopes(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """List per-responsibility scope overrides for a user (Advanced Access)."""
    scopes = db.query(UserResponsibilityScope).filter(
        UserResponsibilityScope.user_id == user_id,
    ).order_by(UserResponsibilityScope.responsibility_code).all()

    return ResponsibilityScopeListResponse(scopes=[
        ResponsibilityScopeResponse(
            id=str(s.id),
            user_id=str(s.user_id),
            responsibility_code=s.responsibility_code,
            scope_type=s.scope_type,
            scope_id=s.scope_id,
        )
        for s in scopes
    ])


@router.post("/user-responsibility-scopes", response_model=ResponsibilityScopeResponse, status_code=201)
async def create_responsibility_scope(
    req: ResponsibilityScopeCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("admin.scopes.manage")),
):
    """Add a per-responsibility scope override (Advanced Access)."""
    claims = ctx
    tenant_id = claims.get("tenant_id")

    scope = UserResponsibilityScope(
        id=uuid.uuid4(),
        user_id=req.user_id,
        tenant_id=tenant_id,
        responsibility_code=req.responsibility_code,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
    )
    db.add(scope)
    db.commit()
    db.refresh(scope)
    logger.info(f"Advanced scope created: {scope.id} for user {req.user_id}")
    return ResponsibilityScopeResponse(
        id=str(scope.id),
        user_id=str(scope.user_id),
        responsibility_code=scope.responsibility_code,
        scope_type=scope.scope_type,
        scope_id=scope.scope_id,
    )


@router.delete("/user-responsibility-scopes/{scope_id}", status_code=204)
async def delete_responsibility_scope(
    scope_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("admin.scopes.manage")),
):
    """Remove a per-responsibility scope override."""
    scope = db.query(UserResponsibilityScope).filter(
        UserResponsibilityScope.id == scope_id
    ).first()
    if not scope:
        raise HTTPException(status_code=404, detail="Scope override not found")
    db.delete(scope)
    db.commit()
