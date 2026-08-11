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
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Tenant, User, UserResponsibilityScope,
)
from provisioning_service.core.db_config import get_db
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
