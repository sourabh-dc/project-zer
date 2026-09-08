"""
Setup checklist — "Complete Your Setup" dashboard widget.

Returns the eight onboarding items with done/pending state, per-item
counts, and an equal-weighted completion percentage.

Items (design order):
  1. Business Details   — company identity on the tenant record
  2. Tenant Details     — operational profile (currency/timezone)
  3. Departments        — first OrgUnit
  4. Cost Centers       — first CostCentre
  5. Roles              — a custom role exists or any role assigned
  6. Users              — more than the creator
  7. Vendors            — first active Vendor
  8. Products           — first active Product
"""
from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    Tenant, User, OrgUnit, CostCentre, Product, Vendor,
    TenantRole, UserRole, TenantUserRole,
)
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import decode_jwt_with_settings

router = APIRouter(prefix="/tenants", tags=["setup-status"])


class SetupItem(BaseModel):
    key: str
    title: str
    description: str
    done: bool
    count: int = 0


class SetupStatusResponse(BaseModel):
    tenant_id: str
    total: int
    completed: int
    percent: int = Field(ge=0, le=100)
    items: List[SetupItem] = Field(default_factory=list)


@router.get("/{tenant_id}/setup-status", response_model=SetupStatusResponse)
async def get_setup_status(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(decode_jwt_with_settings),
):
    """Setup checklist for the dashboard. Any authenticated user of the tenant may view."""
    token_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    if not token_tenant or str(tenant_id) != str(token_tenant):
        raise HTTPException(status_code=403, detail="Not authorised for this tenant")

    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_uuid).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 1. Business Details — company identity filled in
    business_filled = sum(1 for v in (tenant.registration_number, tenant.industry, tenant.phone) if v)
    business_done = bool(tenant.registration_number)  # anchor field

    # 2. Tenant Details — operational profile filled in
    tenant_filled = sum(1 for v in (tenant.default_currency, tenant.timezone, tenant.billing_email) if v)
    tenant_done = bool(tenant.default_currency and tenant.timezone)  # anchor fields

    dept_count = db.query(OrgUnit).filter(
        OrgUnit.tenant_id == tenant_uuid, OrgUnit.status == "active"
    ).count()
    cc_count = db.query(CostCentre).filter(CostCentre.tenant_id == tenant_uuid).count()

    # 5. Roles — custom role created OR any role assigned to a user
    custom_role_count = db.query(TenantRole).filter(TenantRole.tenant_id == tenant_uuid).count()
    assigned_count = db.query(TenantUserRole).filter(TenantUserRole.tenant_id == tenant_uuid).count()
    roles_count = custom_role_count + assigned_count

    user_count = db.query(User).filter(User.tenant_id == tenant_uuid, User.is_active == True).count()
    vendor_count = db.query(Vendor).filter(Vendor.tenant_id == tenant_uuid, Vendor.status == "active").count()
    product_count = db.query(Product).filter(Product.tenant_id == tenant_uuid, Product.active == True).count()

    items = [
        SetupItem(
            key="business_details",
            title="Business Details",
            description="Add your company registration and industry",
            done=business_done,
            count=business_filled,
        ),
        SetupItem(
            key="tenant_details",
            title="Tenant Details",
            description="Set currency, timezone and billing contact",
            done=tenant_done,
            count=tenant_filled,
        ),
        SetupItem(
            key="departments",
            title="Departments",
            description="Create your organisational departments",
            done=dept_count >= 1,
            count=dept_count,
        ),
        SetupItem(
            key="cost_centres",
            title="Cost Centers",
            description="Organize budgets by cost centre",
            done=cc_count >= 1,
            count=cc_count,
        ),
        SetupItem(
            key="roles",
            title="Roles",
            description="Create or assign roles for your team",
            done=roles_count >= 1,
            count=roles_count,
        ),
        SetupItem(
            key="users",
            title="Users",
            description="Invite colleagues to collaborate",
            done=user_count > 1,  # creator alone doesn't count
            count=user_count,
        ),
        SetupItem(
            key="vendors",
            title="Vendors",
            description="Connect your suppliers",
            done=vendor_count >= 1,
            count=vendor_count,
        ),
        SetupItem(
            key="products",
            title="Products",
            description="Build your product catalog",
            done=product_count >= 1,
            count=product_count,
        ),
    ]

    completed = sum(1 for i in items if i.done)
    total = len(items)
    return SetupStatusResponse(
        tenant_id=tenant_id,
        total=total,
        completed=completed,
        percent=round(completed / total * 100),
        items=items,
    )
