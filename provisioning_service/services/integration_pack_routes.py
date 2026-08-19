# ==================================================================================
# INTEGRATION PACK ENDPOINTS (Phase B)
# ==================================================================================
import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from provisioning_service import Models, Schemas
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(
    prefix="/v1",
    tags=["Integration Packs"],
)

@router.get("/integration-packs", response_model=List[Schemas.IntegrationPackOut])
def list_available_integration_packs(db: Session = Depends(get_db)):
    """
    List all available, active integration packs that can be purchased.
    """
    packs = db.query(Models.IntegrationPack).filter(Models.IntegrationPack.is_active == True).all()
    return packs

@router.get("/tenants/{tenant_id}/integration-packs", response_model=List[Schemas.TenantIntegrationPackOut])
def list_tenant_integration_packs(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscriptions.tenant.view")),
):
    """
    List the integration packs a specific tenant is subscribed to.
    """
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this tenant's packs")

    tenant_packs = db.query(Models.TenantIntegrationPack).filter(
        Models.TenantIntegrationPack.tenant_id == uuid.UUID(tenant_id)
    ).all()
    return tenant_packs

@router.post("/tenants/{tenant_id}/integration-packs", status_code=status.HTTP_200_OK)
def purchase_integration_pack(
    tenant_id: str,
    purchase_request: Schemas.IntegrationPackPurchaseRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscriptions.tenant.manage")),
):
    """
    Start an integration pack purchase via Stripe Checkout.

    Returns a checkout URL. The TenantIntegrationPack record is created and
    activated by the payments webhook once payment succeeds.
    """
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this tenant's subscriptions")

    tenant_uuid = uuid.UUID(tenant_id)

    # 1. Verify the pack exists and is active
    pack = db.query(Models.IntegrationPack).filter(
        Models.IntegrationPack.pack_code == purchase_request.pack_code,
        Models.IntegrationPack.is_active == True,
    ).first()
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Integration pack '{purchase_request.pack_code}' not found or inactive.")

    # 2. Reject if already actively subscribed
    existing = db.query(Models.TenantIntegrationPack).filter(
        Models.TenantIntegrationPack.tenant_id == tenant_uuid,
        Models.TenantIntegrationPack.pack_code == purchase_request.pack_code,
    ).first()
    if existing and existing.status == "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Tenant is already subscribed to the '{purchase_request.pack_code}' pack.")

    # 3. Create the Stripe Checkout Session (webhook activates the record on success).
    from provisioning_service.services.payments_routes import _build_pack_checkout_session
    return _build_pack_checkout_session(db, tenant_id, purchase_request.pack_code)


@router.post("/tenants/{tenant_id}/integration-packs/{pack_code}/share", response_model=Schemas.TenantIntegrationPackOut)
def share_integration_pack(
    tenant_id: str,
    pack_code: str,
    share_request: Schemas.IntegrationPackShareRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscriptions.tenant.manage")),
):
    """Phase C4 — shared integration hub.

    Toggle whether an active pack subscription cascades to all sub-tenants
    of this (distributor) tenant. Gated on the ``shared.integration.hub``
    plan feature.
    """
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this tenant's subscriptions")

    from provisioning_service.core.entitlement_helpers import load_tenant_features
    active, _plan, _name, features = load_tenant_features(db, tenant_id)
    if not active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active subscription")
    if "shared.integration.hub" not in features:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sharing packs with sub-tenants requires the Distributor Platform plan",
        )

    pack = db.query(Models.TenantIntegrationPack).filter(
        Models.TenantIntegrationPack.tenant_id == uuid.UUID(tenant_id),
        Models.TenantIntegrationPack.pack_code == pack_code,
        Models.TenantIntegrationPack.status == "active",
    ).first()
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active pack subscription not found")

    pack.shared_with_subtenants = share_request.shared
    db.commit()
    db.refresh(pack)
    logger.info(f"Pack '{pack_code}' sharing for tenant {tenant_id} set to {share_request.shared}")
    return pack


@router.post("/tenants/{tenant_id}/integration-packs/{pack_code}/cancel", response_model=Schemas.TenantIntegrationPackOut)
def cancel_integration_pack(
    tenant_id: str,
    pack_code: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("subscriptions.tenant.manage")),
):
    """Cancel a tenant's integration pack subscription."""
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this tenant's subscriptions")

    tenant_uuid = uuid.UUID(tenant_id)
    pack = db.query(Models.TenantIntegrationPack).filter(
        Models.TenantIntegrationPack.tenant_id == tenant_uuid,
        Models.TenantIntegrationPack.pack_code == pack_code,
    ).first()
    if not pack or pack.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active pack subscription not found")

    # Best-effort cancel in Stripe, then mark locally.
    try:
        import stripe
        from provisioning_service.core.config import SETTINGS
        stripe.api_key = SETTINGS.STRIPE_SECRET_KEY
        if pack.stripe_subscription_id:
            stripe.Subscription.delete(pack.stripe_subscription_id)
    except Exception as _e:
        logger.warning(f"Stripe cancellation failed for pack '{pack_code}': {_e}")

    pack.status = "cancelled"
    pack.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pack)
    return pack
