"""
Setup checklist — "Complete Your Setup" dashboard widget.

Returns the six onboarding items with done/pending state, per-item
counts, and an equal-weighted completion percentage.
"""
from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service.Models import (
    User, SiteTenant, CostCentre, Product, Vendor, ApprovalPolicy,
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

    user_count = db.query(User).filter(User.tenant_id == tenant_uuid, User.is_active == True).count()
    site_count = db.query(SiteTenant).filter(SiteTenant.tenant_id == tenant_uuid).count()
    cc_count = db.query(CostCentre).filter(CostCentre.tenant_id == tenant_uuid).count()
    product_count = db.query(Product).filter(Product.tenant_id == tenant_uuid, Product.active == True).count()
    vendor_count = db.query(Vendor).filter(Vendor.tenant_id == tenant_uuid, Vendor.status == "active").count()
    policy_count = db.query(ApprovalPolicy).filter(
        ApprovalPolicy.tenant_id == tenant_uuid, ApprovalPolicy.is_active == True
    ).count()

    items = [
        SetupItem(
            key="team_members",
            title="Add team members",
            description="Invite colleagues to collaborate",
            done=user_count > 1,  # creator alone doesn't count
            count=user_count,
        ),
        SetupItem(
            key="sites",
            title="Add sites",
            description="Set up your business locations",
            done=site_count >= 1,
            count=site_count,
        ),
        SetupItem(
            key="cost_centres",
            title="Create cost centres",
            description="Organize budgets by department",
            done=cc_count >= 1,
            count=cc_count,
        ),
        SetupItem(
            key="products",
            title="Add products",
            description="Build your product catalog",
            done=product_count >= 1,
            count=product_count,
        ),
        SetupItem(
            key="vendors",
            title="Add vendors",
            description="Connect your suppliers",
            done=vendor_count >= 1,
            count=vendor_count,
        ),
        SetupItem(
            key="approval_groups",
            title="Create approval groups",
            description="Set up spending approval workflows",
            done=policy_count >= 1,
            count=policy_count,
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
