# ==================================================================================
# TENANT BRANDING ENDPOINTS (Phase C3 — White-Label Experience)
# ==================================================================================
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service import Models
from provisioning_service.core.db_config import get_db
from provisioning_service.core.entitlement_helpers import load_tenant_features
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(tags=["Branding"])

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")


class BrandingOut(BaseModel):
    tenant_id: str
    display_name: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    primary_hover_color: Optional[str] = None
    login_background_url: Optional[str] = None
    custom_domain: Optional[str] = None
    support_email: Optional[str] = None
    login_message: Optional[str] = None
    is_default: bool = False


class BrandingUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    favicon_url: Optional[str] = Field(default=None, max_length=500)
    primary_color: Optional[str] = Field(default=None, max_length=9)
    primary_hover_color: Optional[str] = Field(default=None, max_length=9)
    login_background_url: Optional[str] = Field(default=None, max_length=500)
    custom_domain: Optional[str] = Field(default=None, max_length=255)
    support_email: Optional[str] = Field(default=None, max_length=255)
    login_message: Optional[str] = Field(default=None, max_length=500)


def _to_out(b: Models.TenantBranding, is_default: bool = False) -> BrandingOut:
    return BrandingOut(
        tenant_id=str(b.tenant_id),
        display_name=b.display_name,
        logo_url=b.logo_url,
        favicon_url=b.favicon_url,
        primary_color=b.primary_color,
        primary_hover_color=b.primary_hover_color,
        login_background_url=b.login_background_url,
        custom_domain=b.custom_domain,
        support_email=b.support_email,
        login_message=b.login_message,
        is_default=is_default,
    )


def _default_branding(tenant_id: str) -> BrandingOut:
    return BrandingOut(tenant_id=str(tenant_id), is_default=True)


@router.get("/tenants/{tenant_id}/branding", response_model=BrandingOut)
def get_tenant_branding(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscriptions.tenant.view")),
):
    """Fetch the tenant's branding. Falls back to platform defaults."""
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tenant")

    branding = db.query(Models.TenantBranding).filter(
        Models.TenantBranding.tenant_id == uuid.UUID(tenant_id)
    ).first()
    if not branding:
        return _default_branding(tenant_id)
    return _to_out(branding)


@router.put("/tenants/{tenant_id}/branding", response_model=BrandingOut)
def upsert_tenant_branding(
    tenant_id: str,
    req: BrandingUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenant.admin")),
):
    """Create or replace the tenant's white-label branding.

    Gated on the ``white.label`` plan feature (Distributor Platform).
    """
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tenant")

    active, _plan, _name, features = load_tenant_features(db, tenant_id)
    if not active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active subscription")
    if "white.label" not in features:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="White-label branding requires the Distributor Platform plan",
        )

    for color in (req.primary_color, req.primary_hover_color):
        if color is not None and not _HEX_COLOR.match(color):
            raise HTTPException(status_code=400, detail=f"Invalid hex colour: {color!r}")

    tenant_uuid = uuid.UUID(tenant_id)

    if req.custom_domain:
        clash = db.query(Models.TenantBranding).filter(
            Models.TenantBranding.custom_domain == req.custom_domain,
            Models.TenantBranding.tenant_id != tenant_uuid,
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail="Custom domain already in use")

    branding = db.query(Models.TenantBranding).filter(
        Models.TenantBranding.tenant_id == tenant_uuid
    ).first()
    if not branding:
        branding = Models.TenantBranding(tenant_id=tenant_uuid)
        db.add(branding)

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(branding, field, value)

    db.commit()
    db.refresh(branding)
    logger.info(f"Branding updated for tenant {tenant_id}")
    return _to_out(branding)


@router.delete("/tenants/{tenant_id}/branding", status_code=204)
def reset_tenant_branding(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenant.admin")),
):
    """Remove custom branding — the tenant falls back to platform defaults."""
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tenant")

    branding = db.query(Models.TenantBranding).filter(
        Models.TenantBranding.tenant_id == uuid.UUID(tenant_id)
    ).first()
    if branding:
        db.delete(branding)
        db.commit()
        logger.info(f"Branding reset for tenant {tenant_id}")


@router.get("/public/branding", response_model=BrandingOut)
def get_public_branding(
    domain: str = Query(..., description="Custom domain to resolve branding for"),
    db: Session = Depends(get_db),
):
    """Unauthenticated branding lookup by custom domain (login-page theming)."""
    branding = db.query(Models.TenantBranding).filter(
        Models.TenantBranding.custom_domain == domain
    ).first()
    if not branding:
        raise HTTPException(status_code=404, detail="No branding for this domain")
    return _to_out(branding)
