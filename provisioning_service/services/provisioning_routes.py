import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List
import secrets
import bcrypt
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, Role, User, UserIdentity, Invitation, Vendor, Site, Store, CostCentre, UserCostCentre, \
    SpendingEvent, SiteTenant, \
    OrgUnit, UserOrgAssignment, UserRole, RolePermission, Permission, TenantRole, TenantRolePermission, TenantUserRole, \
    TenantRoleScope, RoleAuditEvent, ApprovedRangeOrgUnit, \
    CostCenterBudget, VendorUser
from provisioning_service.Schemas import UserContext, SiteRequest, StoreRequest, \
    CostCentreRequest, VendorRequest, OrgUnitRequest, OrgUnitAssignmentRequest, AssignRoleRequest, \
    RoleRequest, TenantUpdateRequest, TenantRoleRequest, TenantRolePermissionRequest, TenantRoleAssignRequest, \
    TenantRoleUpdateRequest, TenantRolePermissionsReplaceRequest, TenantRoleScopeRequest, \
    VendorUserCreate, VendorUserUpdate, InvitationRequest, InvitationResponse, InvitationListResponse, \
    SiteUpdateRequest, StoreUpdateRequest, UserUpdateRequest, VendorUpdateRequest, CostCentreUpdateRequest

from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.entitlement_helpers import record_feature_usage, enforce_active_user_limit
from provisioning_service.core.helpers.resource_loaders import (
    site_quota_resource,
    store_quota_resource,
    user_quota_resource,
    vendor_quota_resource,
    cost_centre_quota_resource,
)
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration
from provisioning_service.utils.redis_client import redis_client

router = APIRouter(prefix="/provisioning", tags=["Provisioning Service"])

def compute_next_reset(period: str, from_date: Optional[date] = None) -> Optional[date]:
    """Compute the next reset date based on a recurring period."""
    if not from_date:
        from_date = date.today()
    period = (period or "none").lower()
    if period == "daily":
        return from_date + timedelta(days=1)
    if period == "weekly":
        return from_date + timedelta(days=7)
    if period == "monthly":
        return from_date + timedelta(days=30)
    if period == "yearly":
        return from_date + timedelta(days=365)
    return None

"""
ZeroQue Provisioning Service - Simplified Production Version

A clean, powerful API for multi-tenant provisioning with PostgreSQL RLS.
"""
# ==================================================================================
# API ENDPOINTS
# ==================================================================================
@router.get("/tenants")
async def list_tenants(
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List all tenants with pagination"""
    total = db.query(Tenant).filter(Tenant.active == True).count()
    tenants = (
        db.query(Tenant)
        .filter(Tenant.active == True)
        .order_by(Tenant.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    return {
        "tenants": [
            {
                "tenant_id": str(t.tenant_id),
                "name": t.tenant_name,
                "type": t.tenant_type,
                "created_at": t.created_at.isoformat()
            }
            for t in tenants
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/tenants/{tenant_id}")
async def get_tenant(
        tenant_id: str,
        db: Session = Depends(get_db)
):
    """Get a specific tenant by ID"""
    try:
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.tenant_name,
            "type": tenant.tenant_type,
            "active": tenant.active,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/tenants/{tenant_id}")
async def update_tenant(
        req: TenantUpdateRequest,
        db: Session = Depends(get_db),
        policy=Depends(require_policy("tenant.update")),
):
    """Update a tenant's information"""
    try:
        # Find tenant
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Update fields
        print(req.active.lower())
        if req.name:
            # Check if new name conflicts
            existing = db.query(Tenant).filter(
                Tenant.tenant_name == req.name,
                Tenant.tenant_id != uuid.UUID(req.tenant_id)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="Tenant name already exists")
            tenant.tenant_name = req.name
            tenant.tenant_type = req.type,
            tenant.registration_number = req.registration_number,
            tenant.active = True if req.active.lower() == "true" else False
            tenant.phone = req.phone
            tenant.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(tenant)

        # Clear cache
        if redis_client:
            try:
                redis_client.delete(f"tenant:{req.tenant_id}")
            except Exception as e:
                logger.warning(f"Cache clear failed: {e}")

        logger.info(f"✅ Updated tenant: {tenant.tenant_id}")

        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.tenant_name,
            "type": tenant.tenant_type,
            "active": tenant.active,
            "updated_at": tenant.updated_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="update_tenant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="update_tenant", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="update_tenant", status="error").inc()
        logger.error(f"❌ Update tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/tenants/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenants.create")),
    policy=Depends(require_policy("tenant.delete", resource_from="none")),
):
    """Soft-delete a tenant (deactivate). Cascades deactivation to sites, stores and users."""
    try:
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        tenant.active = False
        tenant.updated_at = datetime.now(timezone.utc)

        # Deactivate all sites linked to this tenant
        site_ids = [
            st.site_id
            for st in db.query(SiteTenant).filter(SiteTenant.tenant_id == uuid.UUID(tenant_id)).all()
        ]
        if site_ids:
            db.query(Site).filter(Site.site_id.in_(site_ids)).update(
                {"active": False, "updated_at": datetime.now(timezone.utc)},
                synchronize_session="fetch",
            )

        # Deactivate all stores for this tenant
        db.query(Store).filter(Store.tenant_id == uuid.UUID(tenant_id)).update(
            {"active": False, "updated_at": datetime.now(timezone.utc)},
            synchronize_session="fetch",
        )

        # Deactivate all users for this tenant
        db.query(User).filter(User.tenant_id == uuid.UUID(tenant_id)).update(
            {"is_active": False, "updated_at": datetime.now(timezone.utc)},
            synchronize_session="fetch",
        )

        db.commit()

        # Clear cache
        if redis_client:
            try:
                redis_client.delete(f"tenant:{tenant_id}")
            except Exception:
                pass

        logger.info(f"✅ Soft-deleted tenant {tenant_id} and cascaded deactivation")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete tenant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sites", status_code=201)
async def create_site(
        req: SiteRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("sites.manage")),
        policy=Depends(require_policy("site.create", resource_loader=site_quota_resource)),
):
    """Create a new site and associate it with a tenant"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Create a site (no tenant_id here)

        site = Site(
            site_id=uuid.uuid4(),
            name=req.name,
            site_type=req.type,
            active=bool(getattr(req, "active", True)),
            currency=getattr(req, "currency", None),
            timezone=getattr(req, "timezone", None),
            language=getattr(req, "language", None),
            phone=getattr(req, "phone", None),
            fax=getattr(req, "fax", None),
            email=getattr(req, "email", None),
            url=getattr(req, "url", None),
            logo_url=getattr(req, "logo_url", None),
            primary_billing_address=getattr(req, "primary_billing_address", None),
            primary_shipping_address=getattr(req, "primary_shipping_address", None),
            shipping_addresses=getattr(req, "shipping_addresses", None),
            geo=getattr(req, "geo", None),
            external_id=getattr(req, "external_id", None),
            is_headquarter=bool(getattr(req, "is_headquarter", False))
        )

        db.add(site)
        db.flush()  # Get site_id
        
        # Create a site-tenant relationship
        site_tenant = SiteTenant(
            id=uuid.uuid4(),
            site_id=site.site_id,
            tenant_id=uuid.UUID(req.tenant_id)
        )
        db.add(site_tenant)
        db.commit()
        db.refresh(site)
        
        # Record feature usage
        record_feature_usage(db, req.tenant_id, "multi.site", count=1)

        logger.info(f"Created site: {site.site_id} ({site.name}) for tenant: {req.tenant_id}")

        return {
            "site_id": str(site.site_id),
            "name": site.name,
            "site_type": site.site_type,
            "created_at": site.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_site", status="error").inc()
        raise
    except IntegrityError as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"Site creation IntegrityError: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid tenant reference: {str(e)}")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"Site creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/sites/{site_id}/tenants/{tenant_id}", status_code=201)
async def add_tenant_to_site(
    site_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    user = Depends(check_user_authorization('tenant.admin')),
    policy=Depends(require_policy("site.assign_tenant", resource_from="none")),
):
    """Allow a site to be managed by an additional tenant"""
    try:
        # Verify site exists
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Check if the association already exists
        existing = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == uuid.UUID(tenant_id)
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="Site is already associated with this tenant")
        
        # Create association
        site_tenant = SiteTenant(
            id=uuid.uuid4(),
            site_id=uuid.UUID(site_id),
            tenant_id=uuid.UUID(tenant_id)
        )
        db.add(site_tenant)
        db.commit()
        
        logger.info(f"✅ Added tenant {tenant_id} to site {site_id}")
        
        return {
            "site_id": site_id,
            "tenant_id": tenant_id,
            "associated": True
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Add tenant to site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/sites/{site_id}/tenants")
async def list_site_tenants(
    site_id: str,
    db: Session = Depends(get_db),
    user = Depends(check_user_authorization('tenant.admin'))):
    """List all tenants associated with a site"""
    try:
        # Verify site exists and is accessible by the user's tenant
        site_access = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == user["tenant_id"]
        ).first()
        
        if not site_access:
            raise HTTPException(status_code=404, detail="Site not found or not accessible by your tenant")
        
        # Get all tenants for the site
        tenants = db.query(Tenant).join(
            SiteTenant, Tenant.tenant_id == SiteTenant.tenant_id
        ).filter(
            SiteTenant.site_id == uuid.UUID(site_id)
        ).all()
        
        return {
            "site_id": site_id,
            "tenants": [
                {
                    "tenant_id": str(t.tenant_id),
                    "name": t.tenant_name,
                    "type": t.tenant_type,
                    "created_at": t.created_at.isoformat()
                }
                for t in tenants
            ],
            "total": len(tenants)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ List site tenants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/sites/{site_id}/tenants/{tenant_id}", status_code=204)
async def remove_tenant_from_site(
    site_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("site.remove_tenant", resource_from="none")),
):
    """Remove a tenant from a site"""
    try:
        # Find the association
        site_tenant = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == uuid.UUID(tenant_id)
        ).first()

        if not site_tenant:
            raise HTTPException(status_code=404, detail="Site-tenant association not found")

        # Prevent removing the last tenant
        tenant_count = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id)
        ).count()
        
        if tenant_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the only tenant from a site")

        db.delete(site_tenant)
        db.commit()

        logger.info(f"✅ Removed tenant {tenant_id} from site {site_id}")

        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID or tenant ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Remove tenant from site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
        
@router.get("/sites")
async def list_sites(
        tenant_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization('tenant.admin'))
):
    """List sites with optional tenant filtering"""
    try:
        # Start with SiteTenant join to support many-to-many
        q = db.query(Site).join(SiteTenant, Site.site_id == SiteTenant.site_id)
        
        # If tenant_id provided, filter by it; otherwise filter by user's tenant
        # ctx can be a dict from check_user_authorization; support both
        ctx_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
        if tenant_id:
            q = q.filter(SiteTenant.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(SiteTenant.tenant_id == ctx_tenant)

        total = q.count()
        sites = q.order_by(Site.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "sites": [
                {
                    "site_id": str(s.site_id),
                    "name": s.name,
                    "site_type": s.site_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in sites
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List sites failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sites/{site_id}")
async def get_site(site_id: str, db: Session = Depends(get_db)):
    """Get a single site by ID"""
    try:
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        return {
            "site_id": str(site.site_id),
            "name": site.name,
            "site_type": site.site_type,
            "active": site.active,
            "currency": site.currency,
            "timezone": site.timezone,
            "language": site.language,
            "phone": site.phone,
            "fax": site.fax,
            "email": site.email,
            "url": site.url,
            "logo_url": site.logo_url,
            "primary_billing_address": site.primary_billing_address,
            "primary_shipping_address": site.primary_shipping_address,
            "geo": site.geo,
            "external_id": site.external_id,
            "is_headquarter": site.is_headquarter,
            "created_at": site.created_at.isoformat(),
            "updated_at": site.updated_at.isoformat() if site.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/sites/{site_id}")
async def update_site(
    site_id: str,
    req: SiteUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("sites.manage")),
    policy=Depends(require_policy("site.update")),
):
    """Update an existing site"""
    try:
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        # Map schema field → model field
        field_map = {"site_type": "site_type"}
        for key, value in update_data.items():
            model_key = field_map.get(key, key)
            setattr(site, model_key, value)

        site.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(site)

        # Outbox audit event
        try:
            _st = db.query(SiteTenant).filter(SiteTenant.site_id == site.site_id).first()
            _tid = _st.tenant_id if _st else uuid.uuid4()
            create_outbox_event(
                db, _tid, "site.updated",
                {"site_id": str(site.site_id), "name": site.name, "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for site.updated: {_oe}")

        logger.info(f"✅ Updated site: {site.site_id}")
        return {
            "site_id": str(site.site_id),
            "name": site.name,
            "site_type": site.site_type,
            "active": site.active,
            "updated_at": site.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/sites/{site_id}", status_code=204)
async def delete_site(
    site_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("sites.manage")),
    policy=Depends(require_policy("site.delete", resource_from="none")),
):
    """Soft-delete a site (deactivate it)"""
    try:
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        # Check if stores are still linked
        store_count = db.query(Store).filter(Store.site_id == site.site_id, Store.active == True).count()
        if store_count > 0:
            raise HTTPException(status_code=400, detail=f"Cannot delete site — {store_count} active store(s) still linked")

        site.active = False
        site.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            _st = db.query(SiteTenant).filter(SiteTenant.site_id == site.site_id).first()
            _tid = _st.tenant_id if _st else uuid.uuid4()
            create_outbox_event(db, _tid, "site.deleted", {"site_id": site_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for site.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted site: {site_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete site failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/stores", status_code=201)
async def create_store(
        req: StoreRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("stores.manage")),
        policy=Depends(require_policy("store.create", resource_loader=store_quota_resource)),
):
    """Create a new store under a site for the user's tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()

        # Verify site exists and is accessible by the user's tenant
        if req.site_id:
            site_tenant = db.query(SiteTenant).filter(
                SiteTenant.site_id == uuid.UUID(req.site_id),
                SiteTenant.tenant_id == req.tenant_id
            ).first()

            if not site_tenant:
                raise HTTPException(
                    status_code=404,
                    detail="Site not found or not accessible by your tenant"
                )

        # Create store
        store = Store(
            store_id=uuid.uuid4(),
            site_id=uuid.UUID(req.site_id) if getattr(req, "site_id", None) else None,
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            store_type=req.store_type,
            active=bool(getattr(req, "active", True)),
            currency=getattr(req, "currency", None),
            timezone=getattr(req, "timezone", None),
            phone=getattr(req, "phone", None),
            email=getattr(req, "email", None),
            url=getattr(req, "url", None),
            logo_url=getattr(req, "logo_url", None),
            primary_shipping_address=getattr(req, "primary_shipping_address", None),
            pickup_address=getattr(req, "pickup_address", None),
            geo=getattr(req, "geo", None),
            external_id=getattr(req, "external_id", None),
            fulfillment_mode=getattr(req, "fulfillment_mode", None),
            inventory_policy=getattr(req, "inventory_policy", None)
        )
        db.add(store)
        db.commit()
        db.refresh(store)
        
        # Record feature usage
        record_feature_usage(db, req.tenant_id, "multi.location", count=1)

        # Outbox audit event
        try:
            create_outbox_event(
                db, req.tenant_id, "store.created",
                {"store_id": str(store.store_id), "name": store.name, "tenant_id": req.tenant_id},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for store.created: {_oe}")

        req_total.labels(operation="create_store", status="success").inc()
        req_duration.labels(operation="create_store").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"Created store: {store.store_id} ({store.name}) for tenant: {req.tenant_id}")

        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id),
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "created_at": store.created_at.isoformat()
        }
    
    except ValueError:
        req_total.labels(operation="create_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except HTTPException:
        req_total.labels(operation="create_store", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid site reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_store", status="error").inc()
        logger.error(f"Store creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/stores/{store_id}", status_code=200)
async def update_store(
    store_id: str,
    req: StoreUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("stores.manage")),
    policy=Depends(require_policy("store.update")),
):
    """Update store information"""
    start = datetime.now()
    try:
        req_total.labels(operation="update_store", status="start").inc()

        store = db.query(Store).filter(Store.store_id == uuid.UUID(store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        for key, value in update_data.items():
            if key == "site_id" and value is not None:
                setattr(store, key, uuid.UUID(value))
            else:
                setattr(store, key, value)

        store.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(store)

        # Outbox audit event
        try:
            create_outbox_event(
                db, store.tenant_id, "store.updated",
                {"store_id": str(store.store_id), "name": store.name, "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for store.updated: {_oe}")

        req_total.labels(operation="update_store", status="success").inc()
        req_duration.labels(operation="update_store").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Updated store: {store.store_id} ({store.name})")

        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id) if store.site_id else None,
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "active": store.active,
            "updated_at": store.updated_at.isoformat()
        }

    except ValueError:
        req_total.labels(operation="update_store", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid store ID format")
    except HTTPException:
        req_total.labels(operation="update_store", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="update_store", status="error").inc()
        logger.error(f"❌ Store update failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/stores")
async def list_stores(
        site_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization('tenant.admin'))
):
    """List stores with optional site filtering"""
    try:
        ctx_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
        q = db.query(Store).filter(Store.tenant_id == ctx_tenant)  # Always filter by user's tenant
        
        if site_id:
            # Verify site access before filtering stores
            site_access = db.query(SiteTenant).filter(
                SiteTenant.site_id == uuid.UUID(site_id),
                SiteTenant.tenant_id == ctx_tenant
            ).first()
            
            if not site_access:
                raise HTTPException(status_code=404, detail="Site not found or not accessible by your tenant")
            
            q = q.filter(Store.site_id == uuid.UUID(site_id))

        total = q.count()
        stores = q.order_by(Store.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "stores": [
                {
                    "store_id": str(s.store_id),
                    "site_id": str(s.site_id),
                    "name": s.name,
                    "store_type": s.store_type,
                    "created_at": s.created_at.isoformat()
                }
                for s in stores
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid site ID format")
    except Exception as e:
        logger.error(f"❌ List stores failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stores/{store_id}")
async def get_store(store_id: str, db: Session = Depends(get_db)):
    """Get a single store by ID"""
    try:
        store = db.query(Store).filter(Store.store_id == uuid.UUID(store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")
        return {
            "store_id": str(store.store_id),
            "tenant_id": str(store.tenant_id),
            "site_id": str(store.site_id) if store.site_id else None,
            "name": store.name,
            "store_type": store.store_type,
            "active": store.active,
            "currency": store.currency,
            "timezone": store.timezone,
            "phone": store.phone,
            "email": store.email,
            "url": store.url,
            "logo_url": store.logo_url,
            "primary_shipping_address": store.primary_shipping_address,
            "pickup_address": store.pickup_address,
            "geo": store.geo,
            "external_id": store.external_id,
            "fulfillment_mode": store.fulfillment_mode,
            "inventory_policy": store.inventory_policy,
            "created_at": store.created_at.isoformat(),
            "updated_at": store.updated_at.isoformat() if store.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid store ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get store failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")




@router.delete("/stores/{store_id}", status_code=204)
async def delete_store(
    store_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("stores.manage")),
    policy=Depends(require_policy("store.delete", resource_from="none")),
):
    """Soft-delete a store (deactivate it)"""
    try:
        store = db.query(Store).filter(Store.store_id == uuid.UUID(store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")

        store.active = False
        store.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, store.tenant_id, "store.deleted", {"store_id": store_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for store.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted store: {store_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid store ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete store failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# INVITATIONS
# ==================================================================================

def _send_invitation_email(to_email: str, token: str, tenant_name: str, expires_at: str):
    """Send an invitation email with the acceptance link."""
    try:
        from azure.communication.email import EmailClient
        from provisioning_service.core.config import SETTINGS

        frontend_base = getattr(SETTINGS, "FRONTEND_URL", None) or "http://localhost:3000"
        accept_url = f"{frontend_base.rstrip('/')}/index.html?token={token}"

        mail_from = "DoNotReply@32c276cf-0d14-43a7-8e89-2e45988729a8.azurecomm.net"
        subject = f"You're invited to join {tenant_name} on ZeroQue"

        plain = (
            f"Hello,\n\n"
            f"You have been invited to join {tenant_name} on ZeroQue.\n\n"
            f"Click the link below to accept the invitation and create your account:\n"
            f"{accept_url}\n\n"
            f"This invitation expires on {expires_at}.\n\n"
            f"If you were not expecting this invitation, you can safely ignore this email.\n"
        )

        connection_string = SETTINGS.EMAIL_CONNECTION_STRING
        client = EmailClient.from_connection_string(connection_string)
        message = {
            "senderAddress": mail_from,
            "recipients": {"to": [{"address": to_email}]},
            "content": {
                "subject": subject,
                "plainText": plain,
                "html": f"""<html>
                  <body style="font-family: Arial, sans-serif; color:#222; line-height:1.5;">
                    <p>Hello,</p>
                    <p>You have been invited to join <strong>{tenant_name}</strong> on ZeroQue.</p>
                    <p><a href="{accept_url}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;">Accept Invitation</a></p>
                    <p>This invitation expires on {expires_at}.</p>
                    <p>If you were not expecting this invitation, you can safely ignore this email.</p>
                  </body>
                </html>"""
            },
        }
        poller = client.begin_send(message)
        poller.result()
        logger.info(f"Invitation email sent to {to_email}")
    except Exception as ex:
        logger.error(f"Failed to send invitation email to {to_email}: {ex}")


@router.post("/invitations", response_model=InvitationResponse, status_code=201)
async def create_invitation(
    req: InvitationRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Create an invitation and send it via email. Only tenant admins can invite."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)
    admin_user_id = ctx.get("sub") or (ctx.get("user_id") if isinstance(ctx, dict) else getattr(ctx, "user_id", None))

    # Verify tenant
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_uuid).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Check for existing pending/accepted invitation for this email
    existing_inv = db.query(Invitation).filter(
        Invitation.tenant_id == tenant_uuid,
        Invitation.email == func.lower(req.email),
        Invitation.status.in_(["pending", "accepted"]),
    ).first()
    if existing_inv:
        raise HTTPException(status_code=409, detail="An active invitation already exists for this email")

    # Check if user already has a User row in this tenant
    existing_identity = db.query(UserIdentity).filter(func.lower(UserIdentity.email) == req.email.lower()).first()
    if existing_identity:
        existing_user = db.query(User).filter(
            User.user_id == existing_identity.user_id,
            User.tenant_id == tenant_uuid,
        ).first()
        if existing_user:
            raise HTTPException(status_code=409, detail="User is already a member of this tenant")

    # Enforce the per-plan active user (seat) limit before reserving a seat
    enforce_active_user_limit(db, tenant_id_str, adding=1)

    # Generate token
    raw_token = secrets.token_urlsafe(48)
    token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)

    invitation = Invitation(
        invitation_id=uuid.uuid4(),
        tenant_id=tenant_uuid,
        email=req.email.lower(),
        token_hash=token_hash,
        status="pending",
        role_code=req.role_code,
        created_by=uuid.UUID(admin_user_id) if isinstance(admin_user_id, str) else None,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    # Send email (fire-and-forget — failure doesn't block the response)
    try:
        _send_invitation_email(req.email, raw_token, tenant.tenant_name, expires_at.isoformat())
    except Exception:
        logger.warning(f"Email send failed for invitation {invitation.invitation_id}, but invitation was created")

    logger.info(f"Invitation created: {invitation.invitation_id} for {req.email}")

    return InvitationResponse(
        invitation_id=str(invitation.invitation_id),
        tenant_id=str(tenant_uuid),
        email=invitation.email,
        status=invitation.status,
        role_code=invitation.role_code,
        expires_at=invitation.expires_at.isoformat(),
        created_at=invitation.created_at.isoformat(),
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    status: Optional[str] = Query(None, description="Filter by status: pending, accepted, expired, revoked"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """List all invitations for the tenant."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)

    q = db.query(Invitation).filter(Invitation.tenant_id == tenant_uuid)
    if status:
        q = q.filter(Invitation.status == status)
    q = q.order_by(Invitation.created_at.desc())

    invitations = q.all()
    return InvitationListResponse(invitations=[
        InvitationResponse(
            invitation_id=str(inv.invitation_id),
            tenant_id=str(inv.tenant_id),
            email=inv.email,
            status=inv.status,
            role_code=inv.role_code,
            expires_at=inv.expires_at.isoformat(),
            created_at=inv.created_at.isoformat(),
        ) for inv in invitations
    ])


@router.post("/invitations/{invitation_id}/resend", status_code=200)
async def resend_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Regenerate the token for a pending invitation and resend the email."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)

    invitation = db.query(Invitation).filter(
        Invitation.invitation_id == uuid.UUID(invitation_id),
        Invitation.tenant_id == tenant_uuid,
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status == "accepted":
        raise HTTPException(status_code=400, detail="Invitation already accepted")

    # Regenerate token
    raw_token = secrets.token_urlsafe(48)
    invitation.token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    invitation.status = "pending"  # reset from expired/revoked
    db.commit()
    db.refresh(invitation)

    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_uuid).first()
    try:
        _send_invitation_email(invitation.email, raw_token, tenant.tenant_name if tenant else "", invitation.expires_at.isoformat())
    except Exception:
        logger.warning(f"Email resend failed for invitation {invitation_id}")

    return {"message": "Invitation resent", "expires_at": invitation.expires_at.isoformat()}


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
):
    """Revoke a pending invitation."""
    tenant_id_str = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
    tenant_uuid = uuid.UUID(tenant_id_str)

    invitation = db.query(Invitation).filter(
        Invitation.invitation_id == uuid.UUID(invitation_id),
        Invitation.tenant_id == tenant_uuid,
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if invitation.status == "accepted":
        raise HTTPException(status_code=400, detail="Cannot revoke an accepted invitation")

    invitation.status = "revoked"
    db.commit()
    return Response(status_code=204)


@router.get("/users")
async def list_users(
        tenant_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization('tenant.admin'))
):
    """List users with optional tenant filtering"""
    try:
        ctx_tenant = ctx.get("tenant_id") if isinstance(ctx, dict) else ctx.tenant_id
        q = db.query(User).filter(User.is_active == True)
        if tenant_id:
            q = q.filter(User.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(User.tenant_id == ctx_tenant)  # Filter by user's tenant by default

        total = q.count()
        users = q.order_by(User.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "users": [
                {
                    "user_id": str(u.user_id),
                    "tenant_id": str(u.tenant_id),
                    "email": u.email,
                    "display_name": u.display_name,
                    "created_at": u.created_at.isoformat()
                }
                for u in users
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List users failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}")
async def get_user(user_id: str, db: Session = Depends(get_db)):
    """Get a single user by ID"""
    from provisioning_service.Models import UserIdentity
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == uuid.UUID(user_id)).first()
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": identity.email if identity else None,
            "first_name": identity.first_name if identity else None,
            "last_name": identity.last_name if identity else None,
            "display_name": user.display_name,
            "phone": user.phone,
            "position": user.position,
            "profile_image": user.profile_image,
            "home_site_id": str(user.home_site_id) if user.home_site_id else None,
            "home_store_id": str(user.home_store_id) if user.home_store_id else None,
            "home_org_unit_id": str(user.home_org_unit_id) if user.home_org_unit_id else None,
            "all_locations": user.all_locations,
            "is_active": user.is_active,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
    policy=Depends(require_policy("user.update")),
):
    """Update an existing user"""
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        for key, value in update_data.items():
            if key in ("home_site_id", "home_store_id", "home_org_unit_id") and value is not None:
                setattr(user, key, uuid.UUID(value))
            else:
                setattr(user, key, value)

        # Update display_name if first/last name changed
        from provisioning_service.Models import UserIdentity
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
        if "first_name" in update_data or "last_name" in update_data:
            if identity:
                if "first_name" in update_data:
                    identity.first_name = update_data["first_name"]
                if "last_name" in update_data:
                    identity.last_name = update_data["last_name"]
                user.display_name = f"{identity.first_name} {identity.last_name}".strip()

        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)

        # Outbox audit event
        try:
            create_outbox_event(
                db, user.tenant_id, "user.updated",
                {"user_id": str(user.user_id), "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user.updated: {_oe}")

        logger.info(f"Updated user: {user.user_id}")
        email = identity.email if identity else ""
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": email,
            "display_name": user.display_name,
            "is_active": user.is_active,
            "updated_at": user.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update user failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("users.manage")),
    policy=Depends(require_policy("user.delete", resource_from="none")),
):
    """Soft-delete a user (deactivate)"""
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, user.tenant_id, "user.deleted", {"user_id": user_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted user: {user_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete user failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vendors", status_code=201)
async def create_vendor(
        req: VendorRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("vendors.manage")),
        policy=Depends(require_policy("vendor.create", resource_loader=vendor_quota_resource)),
):
    """Create a new vendor"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_vendor", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Create vendor
        vendor = Vendor(
            vendor_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            contact_email=req.contact_email,
            description=req.description,
            status="active"
        )
        db.add(vendor)
        db.commit()
        db.refresh(vendor)
        
        # Record feature usage
        record_feature_usage(db, req.tenant_id, "supplier.records", count=1)

        # Outbox audit event
        try:
            create_outbox_event(
                db, req.tenant_id, "vendor.created",
                {"vendor_id": str(vendor.vendor_id), "name": vendor.name, "tenant_id": req.tenant_id},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for vendor.created: {_oe}")

        req_total.labels(operation="create_vendor", status="success").inc()
        req_duration.labels(operation="create_vendor").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"Created vendor: {vendor.vendor_id} ({vendor.name})")

        return {
            "vendor_id": str(vendor.vendor_id),
            "tenant_id": str(vendor.tenant_id),
            "name": vendor.name,
            "contact_email": vendor.contact_email,
            "status": vendor.status,
            "created_at": vendor.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_vendor", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_vendor", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_vendor", status="error").inc()
        logger.error(f"❌ Vendor creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/vendor-user")
async def create_vendor_user(
    payload: VendorUserCreate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor_user.create")),
):
    # uniqueness check (vendor + email)
    existing = (
        db.query(VendorUser)
        .filter(VendorUser.vendor_id == payload.vendor_id, VendorUser.email == payload.email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="vendor user with this email already exists")

    obj = VendorUser(
        vendor_id=payload.vendor_id,
        email=payload.email,
        password_hash=payload.password_hash,
        first_name=payload.first_name,
        role=payload.role,
        active=payload.active,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

@router.get("/vendor-user")
def list_vendor_users(
    vendor_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(VendorUser)
    if vendor_id:
        q = q.filter(VendorUser.vendor_id == vendor_id)
    items = q.order_by(VendorUser.created_at.desc()).limit(limit).offset(offset).all()
    return items

@router.put("/{user_id}")
async def update_vendor_user(
    user_id: uuid.UUID,
    payload: VendorUserUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor_user.update")),
):
    obj = db.query(VendorUser).filter(VendorUser.user_id == user_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="vendor user not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(obj, key, value)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@router.delete("/{user_id}")
async def delete_vendor_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor_user.delete", resource_from="none")),
):
    obj = db.query(VendorUser).filter(VendorUser.user_id == user_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="vendor user not found")
    db.delete(obj)
    db.commit()
    return True

@router.get("/vendors")
async def list_vendors(
        tenant_id: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List vendors with optional tenant filtering"""
    q = db.query(Vendor)
    
    if tenant_id:
        q = q.filter(Vendor.tenant_id == uuid.UUID(tenant_id))

    total = q.count()
    vendors = q.order_by(Vendor.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "vendors": [
            {
                "vendor_id": str(v.vendor_id),
                "tenant_id": str(v.tenant_id),
                "name": v.name,
                "status": v.status,
                "created_at": v.created_at.isoformat()
            }
            for v in vendors
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str, db: Session = Depends(get_db)):
    """Get a single vendor by ID"""
    try:
        vendor = db.query(Vendor).filter(Vendor.vendor_id == uuid.UUID(vendor_id)).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return {
            "vendor_id": str(vendor.vendor_id),
            "tenant_id": str(vendor.tenant_id),
            "name": vendor.name,
            "contact_email": vendor.contact_email,
            "description": vendor.description,
            "status": vendor.status,
            "created_at": vendor.created_at.isoformat(),
            "updated_at": vendor.updated_at.isoformat() if vendor.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get vendor failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/vendors/{vendor_id}")
async def update_vendor(
    vendor_id: str,
    req: VendorUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.update")),
):
    """Update an existing vendor"""
    try:
        vendor = db.query(Vendor).filter(Vendor.vendor_id == uuid.UUID(vendor_id)).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        for key, value in update_data.items():
            setattr(vendor, key, value)

        vendor.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(vendor)

        # Outbox audit event
        try:
            create_outbox_event(
                db, vendor.tenant_id, "vendor.updated",
                {"vendor_id": str(vendor.vendor_id), "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for vendor.updated: {_oe}")

        logger.info(f"✅ Updated vendor: {vendor.vendor_id}")
        return {
            "vendor_id": str(vendor.vendor_id),
            "tenant_id": str(vendor.tenant_id),
            "name": vendor.name,
            "status": vendor.status,
            "updated_at": vendor.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update vendor failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/vendors/{vendor_id}", status_code=204)
async def delete_vendor(
    vendor_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.delete", resource_from="none")),
):
    """Soft-delete a vendor (set status to inactive)"""
    try:
        vendor = db.query(Vendor).filter(Vendor.vendor_id == uuid.UUID(vendor_id)).first()
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        vendor.status = "inactive"
        vendor.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, vendor.tenant_id, "vendor.deleted", {"vendor_id": vendor_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for vendor.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted vendor: {vendor_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid vendor ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete vendor failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/cost-centres", status_code=201)
async def create_cost_centre(
        req: CostCentreRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("costcentre.manage")),
        policy=Depends(require_policy("cost_centre.create", resource_loader=cost_centre_quota_resource)),
):
    """Create a new cost centre"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify manager user exists (if provided)
        owner_user_id = None
        if req.owner_user_id:
            manager = db.query(User).filter(User.user_id == uuid.UUID(req.owner_user_id)).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager user not found")
            owner_user_id = uuid.UUID(req.owner_user_id)

        # Create a cost centre
        cc = CostCentre(
            cost_centre_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            code=req.code,
            name=req.name,
            description=getattr(req, "description", None),
            owner_user_id=uuid.UUID(req.owner_user_id) if getattr(req, "owner_user_id", None) else None,
            is_active=bool(getattr(req, "is_active", getattr(req, "active", True)))
        )
        db.add(cc)
        db.commit()
        db.refresh(cc)

        cc_budget = CostCenterBudget(budget_id=uuid.uuid4(), cost_centre_id=cc.cost_centre_id,
                                     tenant_id=req.tenant_id, budget_amount_minor=req.budget_amount_minor,
                                     fiscal_year=req.fiscal_year, period_start=req.period_start, allocated_to_users_minor=0,
                                     period_end=req.period_end, period_type=req.period_type, period_number=req.period_number,
                                     remaining_to_allocate_minor=req.budget_amount_minor,status="active",
                                     created_by=req.created_by)
        db.add(cc_budget)
        db.commit()
        db.refresh(cc_budget)

        # Record feature usage
        record_feature_usage(db, req.tenant_id, "cost.centres", count=1)

        # Outbox audit event
        try:
            create_outbox_event(
                db, req.tenant_id, "cost_centre.created",
                {
                    "cost_centre_id": str(cc.cost_centre_id),
                    "name": cc.name,
                    "budget_minor": cc_budget.budget_amount_minor,
                    "tenant_id": req.tenant_id,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for cost_centre.created: {_oe}")

        req_total.labels(operation="create_cost_centre", status="success").inc()
        req_duration.labels(operation="create_cost_centre").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"Created cost centre: {cc.cost_centre_id} ({cc.name})")

        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "name": cc.name,
            "budget_minor": cc_budget.budget_amount_minor,
            "manager_user_id": str(cc.owner_user_id) if cc.owner_user_id else None,
            "status": "Active" if cc.is_active else "Inactive",
            "created_at": cc.created_at.isoformat()
        }
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        logger.error(f"❌ Cost centre creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/cost-centres")
async def list_cost_centres(
        tenant_id: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List cost centres with optional tenant filtering"""
    # Use boolean is_active on the model
    q = db.query(CostCentre).filter(CostCentre.is_active == True)

    if tenant_id:
        q = q.filter(CostCentre.tenant_id == uuid.UUID(tenant_id))

    total = q.count()
    ccs = q.order_by(CostCentre.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "cost_centres": [
            {
                "cost_centre_id": str(cc.cost_centre_id),
                "tenant_id": str(cc.tenant_id),
                "code": cc.code,
                "name": cc.name,
                "description": cc.description,
                "owner_user_id": str(cc.owner_user_id) if cc.owner_user_id else None,
                "is_active": bool(cc.is_active),
                "created_at": cc.created_at.isoformat()
            }
            for cc in ccs
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/cost-centres/{cost_centre_id}")
async def get_cost_centre(cost_centre_id: str, db: Session = Depends(get_db)):
    """Get a single cost centre by ID"""
    try:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "code": cc.code,
            "name": cc.name,
            "description": cc.description,
            "owner_user_id": str(cc.owner_user_id) if cc.owner_user_id else None,
            "is_active": bool(cc.is_active),
            "created_at": cc.created_at.isoformat(),
            "updated_at": cc.updated_at.isoformat() if cc.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cost centre ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get cost centre failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/cost-centres/{cost_centre_id}")
async def update_cost_centre(
    cost_centre_id: str,
    req: CostCentreUpdateRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
    policy=Depends(require_policy("cost_centre.update")),
):
    """Update an existing cost centre"""
    try:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")

        update_data = req.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        for key, value in update_data.items():
            if key == "owner_user_id" and value is not None:
                setattr(cc, key, uuid.UUID(value))
            else:
                setattr(cc, key, value)

        cc.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(cc)

        # Outbox audit event
        try:
            create_outbox_event(
                db, cc.tenant_id, "cost_centre.updated",
                {"cost_centre_id": str(cc.cost_centre_id), "updated_fields": list(update_data.keys())},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for cost_centre.updated: {_oe}")

        logger.info(f"✅ Updated cost centre: {cc.cost_centre_id}")
        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "code": cc.code,
            "name": cc.name,
            "is_active": bool(cc.is_active),
            "updated_at": cc.updated_at.isoformat(),
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Update cost centre failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/cost-centres/{cost_centre_id}", status_code=204)
async def delete_cost_centre(
    cost_centre_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("costcentre.manage")),
    policy=Depends(require_policy("cost_centre.delete", resource_from="none")),
):
    """Soft-delete a cost centre (deactivate)"""
    try:
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")

        # Check if users are still assigned
        assigned_count = db.query(UserCostCentre).filter(
            UserCostCentre.cost_centre_id == cc.cost_centre_id,
            UserCostCentre.is_blocked == False,
        ).count()
        if assigned_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete cost centre — {assigned_count} active user assignment(s) remain",
            )

        cc.is_active = False
        cc.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, cc.tenant_id, "cost_centre.deleted", {"cost_centre_id": cost_centre_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for cost_centre.deleted: {_oe}")

        logger.info(f"✅ Soft-deleted cost centre: {cost_centre_id}")
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cost centre ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Delete cost centre failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# USER BUDGET ENDPOINTS - Cost Centre Assignments & Budget Info
# ==================================================================================

@router.post("/users/{user_id}/cost-centres", status_code=201)
async def assign_user_to_cost_centre(
    user_id: str,
    cost_centre_id: str = Query(..., description="Cost centre ID"),
    allocated_budget_minor: int = Query(0, description="Initial allocated budget in minor units"),
    recurring_budget_minor: int = Query(0, description="Recurring budget amount for resets"),
    recurring_period: str = Query("none", description="Recurring period: none/daily/weekly/monthly/yearly"),
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization("budgets.manage")),
    policy=Depends(require_policy("user_budget.assign", resource_from="none")),
):
    """Assign a user to a cost centre with optional budget allocation (enforces remaining CC budget)"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify cost centre exists
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()

        cc_budget = db.query(CostCenterBudget).filter(CostCenterBudget.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        if not cc_budget:
            raise HTTPException(status_code=404, detail="Cost centre budget not found; create budget first")

        # Check if the assignment already exists
        existing = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id)
        ).first()

        # If already mapped, allow increasing allocation (idempotent update with remaining-budget check)
        if existing:
            current_alloc = existing.allocated_minor or 0
            current_recurring = existing.recurring_amount_minor or 0
            # Update recurring config if provided
            if recurring_budget_minor:
                existing.recurring_amount_minor = recurring_budget_minor
            if recurring_period:
                existing.recurring_period = recurring_period.lower()
                existing.next_recurring_at = compute_next_reset(recurring_period)
            if allocated_budget_minor <= current_alloc:
                db.commit()
                db.refresh(existing)
                return {
                    "user_budget_id": str(existing.user_budget_id),
                    "user_id": user_id,
                    "cost_centre_id": cost_centre_id,
                    "allocated_minor": existing.allocated_minor,
                    "spent_minor": existing.spent_minor,
                    "available_minor": (existing.available_minor if existing.available_minor is not None else (existing.allocated_minor - existing.spent_minor)),
                    "recurring_amount_minor": existing.recurring_amount_minor,
                    "recurring_period": existing.recurring_period,
                    "next_recurring_at": str(existing.next_recurring_at) if existing.next_recurring_at else None
                }
            delta = allocated_budget_minor - current_alloc
            # Remaining = total budget - already allocated to users - total spent
            remaining_cc = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))
            if delta > remaining_cc:
                raise HTTPException(status_code=400, detail="Insufficient cost centre remaining budget")
            # Update budget allocations
            cc_budget.allocated_to_users_minor = (cc_budget.allocated_to_users_minor or 0) + delta
            cc_budget.remaining_to_allocate_minor = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))
            existing.allocated_minor = allocated_budget_minor
            if not existing.next_recurring_at:
                existing.next_recurring_at = compute_next_reset(existing.recurring_period)
            db.commit()
            db.refresh(existing)
            logger.info(f"✅ Updated allocation for user {user_id} in cost centre {cost_centre_id} by {delta}")
            return {
                "user_budget_id": str(existing.user_budget_id),
                "user_id": user_id,
                "cost_centre_id": cost_centre_id,
                "allocated_minor": existing.allocated_minor,
                "spent_minor": existing.spent_minor,
                "available_minor": (existing.available_minor if existing.available_minor is not None else (existing.allocated_minor - existing.spent_minor)),
                "recurring_amount_minor": existing.recurring_amount_minor,
                "recurring_period": existing.recurring_period,
                "next_recurring_at": str(existing.next_recurring_at) if existing.next_recurring_at else None
            }

        # Enforce remaining budget if allocating
        if allocated_budget_minor and allocated_budget_minor > 0:
            # Remaining = total budget - already allocated - total spent
            remaining_cc = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))
            if allocated_budget_minor > remaining_cc:
                raise HTTPException(status_code=400, detail="Insufficient cost centre remaining budget")
            # Increase allocated_to_users (not total_spent) when assigning to a user
            cc_budget.allocated_to_users_minor = (cc_budget.allocated_to_users_minor or 0) + allocated_budget_minor
            cc_budget.remaining_to_allocate_minor = (cc_budget.budget_amount_minor or 0) - ((cc_budget.allocated_to_users_minor or 0) + (cc_budget.total_spent_minor or 0))

        # Create assignment
        user_cc = UserCostCentre(
            cc_budget_id=cc_budget.budget_id,
            user_budget_id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            cost_centre_id=uuid.UUID(cost_centre_id),
            allocated_minor=allocated_budget_minor,
            spent_minor=0,
            available_minor=allocated_budget_minor,
            max_budget_minor=allocated_budget_minor,
            recurring_amount_minor=recurring_budget_minor or allocated_budget_minor,
            recurring_period=recurring_period.lower() if recurring_period else "none",
            next_recurring_at=compute_next_reset(recurring_period)
        )
        db.add(user_cc)
        # Persist both the user assignment and the updated budget
        db.add(cc_budget)
        db.commit()
        db.refresh(user_cc)
        db.refresh(cc_budget)

        # Outbox audit event
        try:
            user_obj = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
            _tid = user_obj.tenant_id if user_obj else uuid.uuid4()
            create_outbox_event(
                db, _tid, "user_cost_centre.assigned",
                {
                    "user_id": user_id,
                    "cost_centre_id": cost_centre_id,
                    "allocated_minor": allocated_budget_minor,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user_cost_centre.assigned: {_oe}")

        logger.info(f"✅ Assigned user {user_id} to cost centre {cost_centre_id} with budget {allocated_budget_minor}")

        return {
            "user_budget_id": str(user_cc.user_budget_id),
            "user_id": user_id,
            "cost_centre_id": cost_centre_id,
            "allocated_minor": allocated_budget_minor,
            "spent_minor": 0,
            "available_minor": allocated_budget_minor,
            "cost_centre_allocated_to_users_minor": cc_budget.allocated_to_users_minor,
            "cost_centre_remaining_to_allocate_minor": cc_budget.remaining_to_allocate_minor
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to assign user to cost centre: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/budget")
async def get_user_budget(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get user's budget information"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get cost centre assignment
        user_cc = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id)
        ).first()

        if not user_cc:
            return {
                "user_id": user_id,
                "has_budget": False,
                "message": "User not assigned to any cost centre"
            }

        # Get cost centre info and budget summary
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == user_cc.cost_centre_id).first()
        cc_budget = db.query(CostCenterBudget).filter(CostCenterBudget.cost_centre_id == user_cc.cost_centre_id).first()

        available = (user_cc.allocated_minor or 0) - (user_cc.spent_minor or 0)

        return {
            "user_id": user_id,
            "has_budget": True,
            "cost_centre_id": str(user_cc.cost_centre_id),
            "cost_centre_name": cc.name if cc else "Unknown",
            "allocated_minor": user_cc.allocated_minor,
            "spent_minor": user_cc.spent_minor,
            "available_minor": available,
            "recurring_amount_minor": user_cc.recurring_amount_minor,
            "recurring_period": user_cc.recurring_period,
            "next_recurring_at": str(user_cc.next_recurring_at) if user_cc.next_recurring_at else None,
            "cost_centre_budget_amount_minor": cc_budget.budget_amount_minor if cc_budget else 0,
            "cost_centre_total_spent_minor": cc_budget.total_spent_minor if cc_budget else 0,
            "cost_centre_available_minor": ((cc_budget.budget_amount_minor or 0) - (cc_budget.total_spent_minor or 0)) if cc_budget else 0
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/budgets/renew", status_code=200)
async def renew_budgets(
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("budgets.manage")),
    policy=Depends(require_policy("budget.renew", resource_from="none")),
):
    """Renew cost centre and user budgets that are due based on recurring settings."""
    today = date.today()
    renewed_cc = 0
    renewed_users = 0
    try:
        # Renew user-level recurring budgets (UserCostCentre)
        ucs = db.query(UserCostCentre).filter(
            UserCostCentre.recurring_period != None,
            UserCostCentre.recurring_period != "none",
            ((UserCostCentre.next_recurring_at == None) | (UserCostCentre.next_recurring_at <= today))
        ).all()

        for uc in ucs:
            # Determine renewal amount: prefer configured recurring_amount_minor, fall back to allocated_minor
            base = (uc.recurring_amount_minor if uc.recurring_amount_minor is not None else uc.allocated_minor) or 0
            uc.allocated_minor = base
            uc.spent_minor = 0
            # update last/next
            try:
                uc.last_reset_date = today
            except Exception:
                # field may not exist on model; ignore if so
                pass
            uc.next_recurring_at = compute_next_reset(uc.recurring_period, today)

            # Emit a spending event for audit
            try:
                db.add(SpendingEvent(
                    event_id=uuid.uuid4(),
                    event_type="budget_renewal",
                    user_id=uc.user_id,
                    cost_centre_id=uc.cost_centre_id,
                    order_id=None,
                    approval_request_id=None,
                    amount_minor=base,
                    currency_code=None,
                    event_metadata={"recurring_period": uc.recurring_period}
                ))
            except Exception:
                # best-effort; don't fail renewal if event model differs
                logger.debug("SpendingEvent add skipped due to model differences")

            renewed_users += 1

        db.commit()
        return {"renewed_cost_centres": 0, "renewed_users": renewed_users, "date": str(today)}
    except Exception as e:
        db.rollback()
        logger.error(f"Budget renewal failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/spending-history")
async def get_user_spending_history(
    user_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get a user's spending history"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get spending events
        events = db.query(SpendingEvent).filter(
            SpendingEvent.user_id == uuid.UUID(user_id)
        ).order_by(SpendingEvent.created_at.desc()).limit(limit).offset(offset).all()

        total = db.query(func.count(SpendingEvent.event_id)).filter(
            SpendingEvent.user_id == uuid.UUID(user_id)
        ).scalar()

        return {
            "user_id": user_id,
            "events": [
                {
                    "event_id": str(e.event_id),
                    "event_type": e.event_type,
                    "amount_minor": e.amount_minor,
                    "currency_code": e.currency_code,
                    "cost_centre_id": str(e.cost_centre_id),
                    "order_id": str(e.order_id) if e.order_id else None,
                    "approval_request_id": str(e.approval_request_id) if e.approval_request_id else None,
                    "metadata": e.event_metadata,
                    "created_at": e.created_at.isoformat()
                }
                for e in events
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get spending history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

'''to fix the below endpoint, get subordinates from cost center'''
@router.get("/users/{user_id}/subordinates")
async def get_user_subordinates(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get a list of users who report to this user"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get manager's org unit assignments
        manager_assignments = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == uuid.UUID(user_id)
        ).all()

        if not manager_assignments:
            return {
                "user_id": user_id,
                "subordinates": [],
                "total": 0
            }

        # Get org unit IDs where this user is assigned
        org_unit_ids = [assignment.org_unit_id for assignment in manager_assignments]

        # Get all users assigned to these org units (excluding the manager)
        subordinate_assignments = db.query(UserOrgAssignment, User).join(
             User, UserOrgAssignment.user_id == User.user_id
         ).filter(
             UserOrgAssignment.org_unit_id.in_(org_unit_ids),
             UserOrgAssignment.user_id != uuid.UUID(user_id),
             User.is_active == True
         ).all()

        # Deduplicate subordinates
        seen_users = set()
        subordinates = []

        for assignment, subordinate in subordinate_assignments:
            if subordinate.user_id not in seen_users:
                seen_users.add(subordinate.user_id)
                subordinates.append({
                    "user_id": str(subordinate.user_id),
                    "email": subordinate.email,
                    "display_name": subordinate.display_name,
                    "org_unit_id": str(assignment.org_unit_id)
                })

        return {
            "user_id": user_id,
            "subordinates": subordinates,
            "total": len(subordinates)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get subordinates: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/roles", status_code=201)
async def create_role(
        req: RoleRequest,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.manage")),
        policy=Depends(require_policy("role.create")),
):
    """Create a new role"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_role", status="start").inc()

        # Check if code exists (if provided)
        if req.code:
            existing = db.query(Role).filter(Role.code == req.code).first()
            if existing:
                raise HTTPException(status_code=409, detail="Role code already exists")

        # Create role
        role = Role(
            role_id=uuid.uuid4(),
            code=req.code,
            description=req.description or ""
        )
        db.add(role)
        db.commit()
        db.refresh(role)

        req_total.labels(operation="create_role", status="success").inc()
        req_duration.labels(operation="create_role").observe(
            (datetime.now() - start).total_seconds()
        )

        # Outbox audit event (system-level: no tenant scope → use role_id as surrogate)
        try:
            create_outbox_event(
                db, uuid.uuid4(), "role.created",
                {"role_id": str(role.role_id), "code": role.code},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for role.created: {_oe}")

        logger.info(f"✅ Created role: {role.role_id} ({role.code})")

        return {
            "role_id": str(role.role_id),
            "name": role.code,
            "code": role.code,
            "description": role.description,
            "created_at": role.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        raise HTTPException(status_code=409, detail="Role code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_role", status="error").inc()
        logger.error(f"❌ Role creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/roles")
async def list_roles(
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0)
):
    """List all roles"""
    total = db.query(Role).count()
    roles = db.query(Role).order_by(Role.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "roles": [
            {
                "role_id": str(r.role_id),
                "name": r.code,
                "code": r.code,
                "description": r.description,
                "created_at": r.created_at.isoformat()
            }
            for r in roles
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }

@router.post("/roles/map-permission", status_code=201)
async def add_permission_to_role(
        role_code: str,
        permission_code: str,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.manage")),
        policy=Depends(require_policy("role.map_permission", resource_from="none")),
):
    """Add permission to a role"""
    try:
        # Check if already exists
        existing = db.query(RolePermission).filter(
            RolePermission.role_code == role_code,
            RolePermission.permission_code == permission_code
        ).first()

        if existing:
            raise HTTPException(status_code=409, detail="Permission already assigned to role")

        rp = RolePermission(
            id=uuid.uuid4(),
            role_code=role_code,
            permission_code=permission_code
        )
        db.add(rp)
        db.commit()

        return {"message": "Permission added to role"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add permission to role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/roles/delete-permission", status_code=204)
async def remove_permission_from_role(
        role_code: str,
        permission_code: str,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.manage")),
        policy=Depends(require_policy("role.unmap_permission", resource_from="none")),
):
    """Remove permission from a role"""
    try:
        assignment = db.query(RolePermission).filter(
            RolePermission.role_code == role_code,
            RolePermission.permission_code == permission_code
        ).first()

        if not assignment:
            raise HTTPException(status_code=404, detail="Permission not assigned to role")

        db.delete(assignment)
        db.commit()
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role or permission ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to remove permission from role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/permissions")
async def get_all_permissions(
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(100, ge=1, le=500, description="Maximum number of records to return"),
        search: Optional[str] = Query(None, description="Search by code or description"),
        db: Session = Depends(get_db)
):
    """
    Get all permissions in the system.

    Returns a paginated list of all available permissions.
    """
    try:
        query = db.query(Permission)

        # Apply search filter if provided
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (Permission.code.ilike(search_pattern)) |
                (Permission.description.ilike(search_pattern))
            )

        # Get total count
        total = query.count()

        # Apply pagination and ordering
        permissions = query.order_by(Permission.code).offset(skip).limit(limit).all()

        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "permissions": [
                {
                    "permission_id": str(p.permission_id),
                    "code": p.code,
                    "description": p.description,
                    "created_at": p.created_at.isoformat() if p.created_at else None
                }
                for p in permissions
            ]
        }
    except Exception as e:
        logger.error(f"Get permissions failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/roles/{role_code}/permissions")
async def get_role_permissions(
        role_code: str,
        db: Session = Depends(get_db)
):
    """Get all permissions for a role (global or tenant-scoped).

    - If ``role_code`` is a UUID, it's treated as a tenant-role ``role_id``.
    - Otherwise it's treated as a global role ``code``.
    """
    # Try to parse as UUID -> tenant role lookup
    try:
        role_id = uuid.UUID(role_code)
        role = db.query(TenantRole).filter(TenantRole.role_id == role_id).first()
        if role:
            perms = db.query(TenantRolePermission, Permission).join(
                Permission, TenantRolePermission.permission_code == Permission.code
            ).filter(
                TenantRolePermission.tenant_role_id == role_id
            ).all()
            return {
                "role_code": role_code,
                "role_type": "tenant",
                "permissions": [
                    {
                        "permission_code": trp.permission_code,
                        "code": p.code,
                        "description": p.description
                    }
                    for trp, p in perms
                ]
            }
    except ValueError:
        pass  # Not a UUID, treat as global role code

    # Global role lookup
    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_code == Permission.code
    ).filter(
        RolePermission.role_code == role_code
    ).all()

    return {
        "role_code": role_code,
        "role_type": "global",
        "permissions": [
            {
                "permission_code": str(rp.permission_code),
                "code": p.code,
                "description": p.description
            }
            for rp, p in role_perms
        ]
    }


# Tenant-scoped roles (custom per tenant; permissions remain global)
# ── Role helpers ──────────────────────────────────────────────────

def _ctx_ids(ctx):
    """Extract (tenant_id, user_id) UUIDs from the auth context."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    user_id = ctx.get("user_id") if isinstance(ctx, dict) else getattr(ctx, "user_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context")
    return uuid.UUID(str(tenant_id)), (uuid.UUID(str(user_id)) if user_id else None)


def _record_role_event(db: Session, tenant_id, role_id, actor_user_id, action: str, lines):
    """Append one audit event for a role. ``lines`` = human-readable changes."""
    if isinstance(lines, str):
        lines = [lines]
    db.add(RoleAuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role_id=role_id,
        actor_user_id=actor_user_id,
        action=action,
        detail="\n".join(lines) if lines else None,
    ))


def _role_scope_payload(db: Session, role_id) -> dict:
    """Role scope resolved to names: {"departments": [...], "cost_centres": [...]}."""
    rows = db.query(TenantRoleScope).filter(TenantRoleScope.tenant_role_id == role_id).all()
    dept_ids = [s.scope_id for s in rows if s.scope_type == "department"]
    cc_ids = [s.scope_id for s in rows if s.scope_type == "cost_centre"]
    dept_names = {
        ou.org_unit_id: ou.name
        for ou in db.query(OrgUnit).filter(OrgUnit.org_unit_id.in_(dept_ids)).all()
    } if dept_ids else {}
    cc_names = {
        c.cost_centre_id: c.name
        for c in db.query(CostCentre).filter(CostCentre.cost_centre_id.in_(cc_ids)).all()
    } if cc_ids else {}
    payload = {"departments": [], "cost_centres": []}
    for s in rows:
        if s.scope_type == "department":
            payload["departments"].append({"id": str(s.scope_id), "name": dept_names.get(s.scope_id)})
        elif s.scope_type == "cost_centre":
            payload["cost_centres"].append({"id": str(s.scope_id), "name": cc_names.get(s.scope_id)})
    return payload


def _role_history_payload(db: Session, role_id, limit: int = 50) -> list:
    """Per-role audit feed: actor, action, details, timestamp — newest first."""
    rows = (
        db.query(RoleAuditEvent, User)
        .outerjoin(User, RoleAuditEvent.actor_user_id == User.user_id)
        .filter(RoleAuditEvent.role_id == role_id)
        .order_by(RoleAuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "actor": u.display_name if u else None,
            "action": e.action,
            "details": e.detail.split("\n") if e.detail else [],
            "timestamp": e.created_at.isoformat() if e.created_at else None,
        }
        for e, u in rows
    ]


@router.post("/tenant-roles", status_code=201)
async def create_tenant_role(
    req: TenantRoleRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.create")),
):
    tenant_id, actor_id = _ctx_ids(ctx)
    existing = db.query(TenantRole).filter(
        TenantRole.tenant_id == tenant_id,
        TenantRole.code == req.code
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Role code already exists for this tenant")

    # Validate permission codes up-front — fail before creating anything
    perm_codes = list(dict.fromkeys(req.permissions or []))  # dedupe, keep order
    if perm_codes:
        found = {
            p.code for p in db.query(Permission).filter(Permission.code.in_(perm_codes)).all()
        }
        unknown = [c for c in perm_codes if c not in found]
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown permission code(s): {', '.join(unknown)}",
            )

    role = TenantRole(
        role_id=uuid.uuid4(),
        tenant_id=tenant_id,
        code=req.code,
        name=req.name or req.code,
        description=req.description,
        category=req.category,
        status="active",
        updated_by=actor_id,
    )
    db.add(role)
    for pc in perm_codes:
        db.add(TenantRolePermission(
            id=uuid.uuid4(),
            tenant_role_id=role.role_id,
            permission_code=pc,
        ))
    _record_role_event(db, tenant_id, role.role_id, actor_id, "created",
                       [f"Created role {role.name} ({role.code})"])
    db.commit()
    db.refresh(role)
    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "category": role.category,
        "status": role.status,
        "is_custom": True,
        "permissions": perm_codes,
    }


@router.post("/tenant-roles/{role_id}/permissions", status_code=201)
async def add_permission_to_tenant_role(
    role_id: str,
    req: TenantRolePermissionRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.add_permission", resource_from="none")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == uuid.UUID(str(tenant_id))
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    perm = db.query(Permission).filter(Permission.code == req.permission_code).first()
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    existing = db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id,
        TenantRolePermission.permission_code == req.permission_code
    ).first()
    if existing:
        return {"role_id": str(role.role_id), "permission_code": req.permission_code, "assigned": True}
    trp = TenantRolePermission(
        id=uuid.uuid4(),
        tenant_role_id=role.role_id,
        permission_code=req.permission_code
    )
    db.add(trp)
    db.commit()
    return {"role_id": str(role.role_id), "permission_code": req.permission_code, "assigned": True}


@router.put("/tenant-roles/{role_id}")
async def update_tenant_role(
    role_id: str,
    req: TenantRoleUpdateRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Update role details (name / description / category) with audit trail."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    changes = []
    update_data = req.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    for field in ("name", "description", "category"):
        if field in update_data:
            old = getattr(role, field)
            new = update_data[field]
            if old != new:
                setattr(role, field, new)
                changes.append(f"Changed {field} from '{old or '—'}' to '{new or '—'}'")

    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    if changes:
        _record_role_event(db, tenant_id, role.role_id, actor_id, "updated", changes)
    db.commit()
    db.refresh(role)
    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "category": role.category,
        "status": role.status,
        "updated_at": role.updated_at.isoformat() if role.updated_at else None,
    }


@router.put("/tenant-roles/{role_id}/permissions")
async def replace_tenant_role_permissions(
    role_id: str,
    req: TenantRolePermissionsReplaceRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Replace the full permission set (wizard save). Diffs recorded to history."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    new_codes = list(dict.fromkeys(req.permissions or []))
    found = {
        p.code for p in db.query(Permission).filter(Permission.code.in_(new_codes)).all()
    } if new_codes else set()
    unknown = [c for c in new_codes if c not in found]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown permission code(s): {', '.join(unknown)}")

    old_codes = {
        trp.permission_code
        for trp in db.query(TenantRolePermission).filter(
            TenantRolePermission.tenant_role_id == role.role_id
        ).all()
    }
    new_set = set(new_codes)
    added = sorted(new_set - old_codes)
    removed = sorted(old_codes - new_set)

    db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id
    ).delete()
    for pc in new_codes:
        db.add(TenantRolePermission(
            id=uuid.uuid4(), tenant_role_id=role.role_id, permission_code=pc,
        ))

    lines = [f"Added {c}" for c in added] + [f"Removed {c}" for c in removed]
    if lines:
        _record_role_event(db, tenant_id, role.role_id, actor_id, "permissions.updated", lines)
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    db.commit()
    return {"role_id": str(role.role_id), "permissions": new_codes,
            "added": added, "removed": removed}


@router.delete("/tenant-roles/{role_id}/permissions/{permission_code}", status_code=200)
async def remove_tenant_role_permission(
    role_id: str,
    permission_code: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Remove a single permission from a tenant role."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    deleted = db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id,
        TenantRolePermission.permission_code == permission_code,
    ).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="Permission not assigned to this role")
    _record_role_event(db, tenant_id, role.role_id, actor_id, "permissions.updated",
                       [f"Removed {permission_code}"])
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    db.commit()
    return {"role_id": str(role.role_id), "removed": permission_code}


@router.put("/tenant-roles/{role_id}/scope")
async def set_tenant_role_scope(
    role_id: str,
    req: TenantRoleScopeRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Replace role scope (departments / cost centres). Empty items = All."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    # Validate targets exist and belong to this tenant
    dept_ids = [uuid.UUID(i.scope_id) for i in req.items if i.scope_type == "department"]
    cc_ids = [uuid.UUID(i.scope_id) for i in req.items if i.scope_type == "cost_centre"]
    bad_types = [i.scope_type for i in req.items if i.scope_type not in ("department", "cost_centre")]
    if bad_types:
        raise HTTPException(status_code=400, detail=f"Unknown scope_type(s): {', '.join(sorted(set(bad_types)))}")
    dept_names = {
        ou.org_unit_id: ou.name
        for ou in db.query(OrgUnit).filter(
            OrgUnit.org_unit_id.in_(dept_ids), OrgUnit.tenant_id == tenant_id,
        ).all()
    } if dept_ids else {}
    cc_names = {
        c.cost_centre_id: c.name
        for c in db.query(CostCentre).filter(
            CostCentre.cost_centre_id.in_(cc_ids), CostCentre.tenant_id == tenant_id,
        ).all()
    } if cc_ids else {}
    missing = [str(d) for d in dept_ids if d not in dept_names] + \
              [str(c) for c in cc_ids if c not in cc_names]
    if missing:
        raise HTTPException(status_code=404, detail=f"Scope target(s) not found: {', '.join(missing)}")

    old_rows = db.query(TenantRoleScope).filter(
        TenantRoleScope.tenant_role_id == role.role_id
    ).all()
    old_set = {(s.scope_type, str(s.scope_id)) for s in old_rows}
    new_set = {(i.scope_type, i.scope_id) for i in req.items}

    db.query(TenantRoleScope).filter(TenantRoleScope.tenant_role_id == role.role_id).delete()
    for i in req.items:
        db.add(TenantRoleScope(
            id=uuid.uuid4(), tenant_role_id=role.role_id,
            scope_type=i.scope_type, scope_id=uuid.UUID(i.scope_id),
        ))

    def _label(stype, sid):
        if stype == "department":
            return dept_names.get(uuid.UUID(sid)) or sid
        return cc_names.get(uuid.UUID(sid)) or sid

    lines = [f"Added {_label(t, s)} to {t}" for t, s in sorted(new_set - old_set)] + \
            [f"Removed {_label(t, s)} from {t}" for t, s in sorted(old_set - new_set)]
    if lines:
        _record_role_event(db, tenant_id, role.role_id, actor_id, "scope.updated", lines)
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    db.commit()
    return {"role_id": str(role.role_id), "scope": _role_scope_payload(db, role.role_id)}


@router.post("/tenant-roles/{role_id}/deactivate")
async def deactivate_tenant_role(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Set role status to inactive (keeps assignments, blocks new ones)."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    if role.status == "inactive":
        return {"role_id": str(role.role_id), "status": "inactive"}
    role.status = "inactive"
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    _record_role_event(db, tenant_id, role.role_id, actor_id, "status.changed",
                       ["Deactivated role"])
    db.commit()
    return {"role_id": str(role.role_id), "status": "inactive"}


@router.post("/tenant-roles/{role_id}/activate")
async def activate_tenant_role(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.update", resource_from="none")),
):
    """Restore an inactive role to active."""
    tenant_id, actor_id = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    if role.status == "active":
        return {"role_id": str(role.role_id), "status": "active"}
    role.status = "active"
    role.updated_at = datetime.now(timezone.utc)
    role.updated_by = actor_id
    _record_role_event(db, tenant_id, role.role_id, actor_id, "status.changed",
                       ["Restored role"])
    db.commit()
    return {"role_id": str(role.role_id), "status": "active"}


@router.get("/tenant-roles/{role_id}/history")
async def get_tenant_role_history(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
):
    """Per-role audit feed, newest first."""
    tenant_id, _ = _ctx_ids(ctx)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == tenant_id,
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    return {"role_id": str(role.role_id), "history": _role_history_payload(db, role.role_id)}


@router.post("/users/{user_id}/tenant-roles", status_code=201)
async def assign_tenant_role_to_user(
    user_id: str,
    req: TenantRoleAssignRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("users.manage")),
    policy=Depends(require_policy("user_role.assign", resource_from="none")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(req.role_id),
        TenantRole.tenant_id == uuid.UUID(str(tenant_id))
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")
    user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
    if not user or str(user.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=404, detail="User not found in tenant")
    existing = db.query(TenantUserRole).filter(
        TenantUserRole.user_id == user.user_id,
        TenantUserRole.tenant_role_id == role.role_id
    ).first()
    if existing:
        return {"status": "ok", "message": "Role already assigned", "user_id": str(user.user_id), "role_id": str(role.role_id)}
    tur = TenantUserRole(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(str(tenant_id)),
        user_id=user.user_id,
        tenant_role_id=role.role_id
    )
    db.add(tur)
    db.commit()
    return {"status": "ok", "user_id": str(user.user_id), "role_id": str(role.role_id)}


@router.get("/tenant-roles")
async def list_tenant_roles(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),  # active | inactive | all (default: all)
    sort: str = Query("created_at"),      # name | code | created_at | users_count
    order: str = Query("desc"),           # asc | desc
    limit: int = Query(100, le=500, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    """List tenant roles with full card data: permissions, scope, users_count."""
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    tid = uuid.UUID(str(tenant_id))

    q = db.query(TenantRole).filter(TenantRole.tenant_id == tid)
    if search:
        like = f"%{search}%"
        q = q.filter((TenantRole.name.ilike(like)) | (TenantRole.code.ilike(like)))
    if category:
        q = q.filter(TenantRole.category == category)
    if status and status != "all":
        q = q.filter(TenantRole.status == status)

    total = q.count()

    sort_col = {
        "name": TenantRole.name,
        "code": TenantRole.code,
        "created_at": TenantRole.created_at,
    }.get(sort, TenantRole.created_at)
    q = q.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    roles = q.offset(offset).limit(limit).all()

    # Permissions for all listed roles in one query
    role_ids = [r.role_id for r in roles]
    permissions_map: dict = {rid: [] for rid in role_ids}
    if role_ids:
        perms = (
            db.query(TenantRolePermission, Permission)
            .join(Permission, TenantRolePermission.permission_code == Permission.code)
            .filter(TenantRolePermission.tenant_role_id.in_(role_ids))
            .all()
        )
        for trp, p in perms:
            permissions_map[trp.tenant_role_id].append({
                "code": trp.permission_code,
                "description": p.description
            })

    # Users count per role
    users_count_map: dict = {}
    if role_ids:
        counts = (
            db.query(TenantUserRole.tenant_role_id, func.count(TenantUserRole.id))
            .filter(TenantUserRole.tenant_role_id.in_(role_ids))
            .group_by(TenantUserRole.tenant_role_id)
            .all()
        )
        users_count_map = {rid: c for rid, c in counts}

    # Scope per role, resolved to names
    scope_map: dict = {rid: {"departments": [], "cost_centres": []} for rid in role_ids}
    if role_ids:
        scope_rows = db.query(TenantRoleScope).filter(
            TenantRoleScope.tenant_role_id.in_(role_ids)
        ).all()
        dept_ids = [s.scope_id for s in scope_rows if s.scope_type == "department"]
        cc_ids = [s.scope_id for s in scope_rows if s.scope_type == "cost_centre"]
        dept_names = {
            ou.org_unit_id: ou.name
            for ou in db.query(OrgUnit).filter(OrgUnit.org_unit_id.in_(dept_ids)).all()
        } if dept_ids else {}
        cc_names = {
            c.cost_centre_id: c.name
            for c in db.query(CostCentre).filter(CostCentre.cost_centre_id.in_(cc_ids)).all()
        } if cc_ids else {}
        for s in scope_rows:
            target = {"id": str(s.scope_id), "name": None}
            if s.scope_type == "department":
                target["name"] = dept_names.get(s.scope_id)
                scope_map[s.tenant_role_id]["departments"].append(target)
            elif s.scope_type == "cost_centre":
                target["name"] = cc_names.get(s.scope_id)
                scope_map[s.tenant_role_id]["cost_centres"].append(target)

    items = [
        {
            "role_id": str(r.role_id),
            "code": r.code,
            "name": r.name or r.code,
            "description": r.description,
            "category": r.category,
            "status": r.status or "active",
            "is_custom": True,
            "permissions": permissions_map.get(r.role_id, []),
            "scope": scope_map.get(r.role_id, {"departments": [], "cost_centres": []}),
            "users_count": users_count_map.get(r.role_id, 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in roles
    ]

    # users_count sort needs the assembled list
    if sort == "users_count":
        items.sort(key=lambda x: x["users_count"], reverse=(order != "asc"))

    return {"roles": items, "total": total, "limit": limit, "offset": offset}


@router.get("/tenant-roles/{role_ref}/detail")
async def get_tenant_role_detail(
    role_ref: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    """Full detail for one tenant role: permissions, assigned users (with
    scopes), and change history.

    ``role_ref`` accepts either the role UUID or its code.
    History is returned empty until role audit events are recorded.
    """
    from provisioning_service.Models import UserResponsibilityScope

    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context")
    tid = uuid.UUID(str(tenant_id))

    # Resolve by UUID, fall back to role code
    role = None
    try:
        role_uuid = uuid.UUID(role_ref)
        role = db.query(TenantRole).filter(
            TenantRole.role_id == role_uuid,
            TenantRole.tenant_id == tid,
        ).first()
    except ValueError:
        pass
    if role is None:
        role = db.query(TenantRole).filter(
            TenantRole.code == role_ref,
            TenantRole.tenant_id == tid,
        ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    # Permissions (with descriptions)
    perm_rows = (
        db.query(TenantRolePermission, Permission)
        .join(Permission, TenantRolePermission.permission_code == Permission.code)
        .filter(TenantRolePermission.tenant_role_id == role.role_id)
        .all()
    )
    permissions = [
        {"code": p.code, "description": p.description}
        for _, p in perm_rows
    ]

    # Assigned users (+ identity for email, + responsibility scopes)
    assignments = (
        db.query(TenantUserRole, User)
        .join(User, TenantUserRole.user_id == User.user_id)
        .filter(TenantUserRole.tenant_role_id == role.role_id)
        .all()
    )
    user_ids = [u.user_id for _, u in assignments]
    identities = {
        i.user_id: i
        for i in db.query(UserIdentity).filter(UserIdentity.user_id.in_(user_ids)).all()
    } if user_ids else {}
    scope_rows = db.query(UserResponsibilityScope).filter(
        UserResponsibilityScope.user_id.in_(user_ids),
        UserResponsibilityScope.tenant_id == tid,
    ).all() if user_ids else []
    scopes_by_user: dict = {}
    for s in scope_rows:
        scopes_by_user.setdefault(s.user_id, []).append({
            "responsibility_code": s.responsibility_code,
            "scope_type": s.scope_type,
            "scope_id": s.scope_id,
        })

    users = [
        {
            "user_id": str(u.user_id),
            "display_name": u.display_name,
            "email": identities[u.user_id].email if u.user_id in identities else None,
            "is_active": u.is_active,
            "assigned_at": tur.created_at.isoformat() if tur.created_at else None,
            "scopes": scopes_by_user.get(u.user_id, []),
        }
        for tur, u in assignments
    ]

    # Role-level scope (departments / cost centres), resolved to names
    scope = _role_scope_payload(db, role.role_id)

    # Per-role audit history
    history = _role_history_payload(db, role.role_id)

    return {
        "role_id": str(role.role_id),
        "code": role.code,
        "name": role.name or role.code,
        "description": role.description,
        "category": role.category,
        "status": role.status or "active",
        "is_custom": True,
        "created_at": role.created_at.isoformat() if role.created_at else None,
        "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        "permissions": permissions,
        "scope": scope,
        "users": users,
        "users_count": len(users),
        "history": history,
    }


@router.delete("/tenant-roles/{role_id}", status_code=204)
async def delete_tenant_role(
    role_id: str,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.delete", resource_from="none")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    role = db.query(TenantRole).filter(
        TenantRole.role_id == uuid.UUID(role_id),
        TenantRole.tenant_id == uuid.UUID(str(tenant_id))
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Tenant role not found")

    # Remove all permission assignments
    db.query(TenantRolePermission).filter(
        TenantRolePermission.tenant_role_id == role.role_id
    ).delete()
    # Remove all user assignments
    db.query(TenantUserRole).filter(
        TenantUserRole.tenant_role_id == role.role_id
    ).delete()
    db.delete(role)
    db.commit()
    return Response(status_code=204)

@router.post("/users/{user_id}/roles", status_code=201)
async def assign_role_to_user(
        user_id: str,
        req: AssignRoleRequest,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.assign")),
        policy=Depends(require_policy("user_role.assign")),
):
    """Assign a role to a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="assign_role", status="start").inc()

        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify role exists
        role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # Check if the assignment already exists (idempotent)
        existing = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(req.role_id),
            UserRole.tenant_id == user.tenant_id
        ).first()

        if existing:
            return {"status": "ok", "message": "Role already assigned", "user_id": user_id, "role_id": str(existing.role_id)}

        # Create assignment with tenant_id from user
        user_role = UserRole(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=uuid.UUID(user_id),
            role_id=uuid.UUID(req.role_id)
        )
        db.add(user_role)
        db.commit()
        db.refresh(user_role)

        # Outbox audit event
        try:
            create_outbox_event(
                db, user.tenant_id, "user_role.assigned",
                {"user_id": user_id, "role_id": req.role_id, "role_code": role.code},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user_role.assigned: {_oe}")

        req_total.labels(operation="assign_role", status="success").inc()
        req_duration.labels(operation="assign_role").observe(
            (datetime.now() - start).total_seconds()
        )

        return {
            "user_id": user_id,
            "role_id": req.role_id,
            "role_name": role.code,
            "assigned": True,
            "created_at": user_role.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="assign_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="assign_role", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        return {"status": "ok", "message": "Role already assigned (integrity)", "user_id": user_id, "role_id": str(req.role_code)}
    except Exception as e:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        logger.error(f"❌ Assign role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/roles")
async def get_user_roles(
        user_id: str,
        db: Session = Depends(get_db)
):
    """Get all roles assigned to a user"""
    from provisioning_service.Models import UserIdentity
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get identity for email
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == uuid.UUID(user_id)).first()

        # Get global roles
        global_roles = (
            db.query(UserRole, Role)
            .join(Role, UserRole.role_id == Role.role_id)
            .filter(UserRole.user_id == uuid.UUID(user_id))
            .all()
        )

        # Get tenant-scoped custom roles
        tenant_roles = (
            db.query(TenantUserRole, TenantRole)
            .join(TenantRole, TenantUserRole.tenant_role_id == TenantRole.role_id)
            .filter(TenantUserRole.user_id == uuid.UUID(user_id))
            .all()
        )

        roles_list = []
        for ur, r in global_roles:
            roles_list.append({
                "role_id": str(r.role_id),
                "role_code": r.code,
                "role_name": r.code,
                "type": "global",
                "assigned_at": ur.created_at.isoformat()
            })
        for tur, tr in tenant_roles:
            roles_list.append({
                "role_id": str(tr.role_id),
                "role_code": tr.code,
                "role_name": tr.code,
                "type": "tenant",
                "assigned_at": tur.created_at.isoformat()
            })

        return {
            "user_id": user_id,
            "email": identity.email if identity else None,
            "display_name": user.display_name,
            "roles": roles_list,
            "total": len(roles_list)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get user roles failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(
        user_id: str,
        role_id: str,
        db: Session = Depends(get_db),
        ctx=Depends(check_user_authorization("roles.assign")),
        policy=Depends(require_policy("user_role.remove", resource_from="none")),
):
    """Remove a role from a user"""
    start = datetime.now()
    try:
        req_total.labels(operation="remove_role", status="start").inc()

        # Find user role assignment (check both global and tenant roles)
        user_role = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id)
        ).first()

        tenant_user_role = None
        if not user_role:
            tenant_user_role = db.query(TenantUserRole).filter(
                TenantUserRole.user_id == uuid.UUID(user_id),
                TenantUserRole.tenant_role_id == uuid.UUID(role_id)
            ).first()

        if not user_role and not tenant_user_role:
            raise HTTPException(status_code=404, detail="Role assignment not found")

        if user_role:
            user = db.query(User).filter(User.user_id == user_role.user_id).first()
            db.delete(user_role)
        else:
            user = db.query(User).filter(User.user_id == tenant_user_role.user_id).first()
            db.delete(tenant_user_role)
        db.commit()

        # Outbox audit event
        try:
            _tid = user.tenant_id if user else uuid.uuid4()
            create_outbox_event(db, _tid, "user_role.removed", {"user_id": user_id, "role_id": role_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for user_role.removed: {_oe}")

        req_total.labels(operation="remove_role", status="success").inc()
        req_duration.labels(operation="remove_role").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Removed role {role_id} from user {user_id}")

        return {
            "user_id": user_id,
            "role_id": role_id,
            "removed": True
        }
    except ValueError:
        req_total.labels(operation="remove_role", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid user ID or role ID format")
    except HTTPException:
        req_total.labels(operation="remove_role", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="remove_role", status="error").inc()
        logger.error(f"❌ Remove role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/org_units")
async def list_org_units(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    parent_org_unit_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List organisational units with optional filters"""
    try:
        q = db.query(OrgUnit)

        if tenant_id:
            q = q.filter(OrgUnit.tenant_id == uuid.UUID(tenant_id))
        if status:
            q = q.filter(OrgUnit.status == status)
        if parent_org_unit_id:
            q = q.filter(OrgUnit.parent_org_unit_id == uuid.UUID(parent_org_unit_id))

        total = q.count()
        org_units = q.order_by(OrgUnit.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "org_units": [
                {
                    "org_unit_id": str(ou.org_unit_id),
                    "tenant_id": str(ou.tenant_id),
                    "name": ou.name,
                    "type": ou.type,
                    "status": ou.status,
                    "parent_org_unit_id": str(ou.parent_org_unit_id) if ou.parent_org_unit_id else None,
                    "code": ou.code,
                    "description": ou.description,
                    "manager_user_id": str(ou.manager_user_id) if ou.manager_user_id else None,
                    "external_id": ou.external_id,
                    "path": ou.path,
                    "depth": ou.depth,
                    "created_at": ou.created_at.isoformat(),
                    "updated_at": ou.updated_at.isoformat() if ou.updated_at else None,
                }
                for ou in org_units
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    except Exception as e:
        logger.error(f"❌ List org units failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/org_units/{org_unit_id}")
async def get_org_unit(org_unit_id: str, db: Session = Depends(get_db)):
    """Get a single organisational unit by ID"""
    try:
        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")
        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "type": ou.type,
            "status": ou.status,
            "parent_org_unit_id": str(ou.parent_org_unit_id) if ou.parent_org_unit_id else None,
            "code": ou.code,
            "description": ou.description,
            "manager_user_id": str(ou.manager_user_id) if ou.manager_user_id else None,
            "external_id": ou.external_id,
            "path": ou.path,
            "depth": ou.depth,
            "created_at": ou.created_at.isoformat(),
            "updated_at": ou.updated_at.isoformat() if ou.updated_at else None,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org unit ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/org_units", status_code=201)
async def create_org_unit(
        req: OrgUnitRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.create")),
):
    """Create a new organisational unit"""
    try:
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Optional parent validation
        parent_id = None
        if getattr(req, 'parent_org_unit_id', None):
            try:
                parent_id = uuid.UUID(req.parent_org_unit_id)
                parent = db.query(OrgUnit).filter(OrgUnit.org_unit_id == parent_id, OrgUnit.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent org unit not found for tenant")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid parent_org_unit_id format")

        manager_uuid = None
        if getattr(req, 'manager_user_id', None):
            try:
                manager_uuid = uuid.UUID(req.manager_user_id)
                manager = db.query(User).filter(User.user_id == manager_uuid, User.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not manager:
                    raise HTTPException(status_code=404, detail="Manager user not found for tenant")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid manager_user_id format")

        ou = OrgUnit(
            org_unit_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            type=req.type,
            status=getattr(req, 'status', 'active'),
            parent_org_unit_id=parent_id,
            code=getattr(req, 'code', None),
            description=getattr(req, 'description', None),
            manager_user_id=manager_uuid,
            external_id=getattr(req, 'external_id', None),
            path=getattr(req, 'path', None),
            depth=getattr(req, 'depth', None)
        )

        db.add(ou)
        db.commit()
        db.refresh(ou)

        # Outbox audit event
        try:
            create_outbox_event(
                db, req.tenant_id, "org_unit.created",
                {"org_unit_id": str(ou.org_unit_id), "name": ou.name, "type": ou.type},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.created: {_oe}")

        logger.info(f"Created org unit: {ou.org_unit_id} ({ou.name}) for tenant: {req.tenant_id}")

        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "type": ou.type,
            "status": ou.status,
            "created_at": ou.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format in request")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Create org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/org_units/{org_unit_id}")
async def update_org_unit(
        org_unit_id: str,
        req: OrgUnitRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.update")),
):
    """Update an existing organisational unit"""
    try:
        try:
            ou_id = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # Ensure tenant matches
        if str(ou.tenant_id) != req.tenant_id:
            raise HTTPException(status_code=403, detail="Tenant mismatch")

        # Update fields
        if getattr(req, 'name', None):
            ou.name = req.name
        if getattr(req, 'type', None):
            ou.type = req.type
        if getattr(req, 'status', None):
            ou.status = req.status

        if getattr(req, 'parent_org_unit_id', None):
            try:
                parent_uuid = uuid.UUID(req.parent_org_unit_id)
                parent = db.query(OrgUnit).filter(OrgUnit.org_unit_id == parent_uuid, OrgUnit.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent org unit not found for tenant")
                ou.parent_org_unit_id = parent_uuid
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid parent_org_unit_id format")

        if getattr(req, 'manager_user_id', None):
            try:
                manager_uuid = uuid.UUID(req.manager_user_id)
                manager = db.query(User).filter(User.user_id == manager_uuid, User.tenant_id == uuid.UUID(req.tenant_id)).first()
                if not manager:
                    raise HTTPException(status_code=404, detail="Manager user not found for tenant")
                ou.manager_user_id = manager_uuid
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid manager_user_id format")

        ou.code = getattr(req, 'code', ou.code)
        ou.description = getattr(req, 'description', ou.description)
        ou.external_id = getattr(req, 'external_id', ou.external_id)
        ou.path = getattr(req, 'path', ou.path)
        ou.depth = getattr(req, 'depth', ou.depth)

        ou.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(ou)

        # Outbox audit event
        try:
            create_outbox_event(
                db, ou.tenant_id, "org_unit.updated",
                {"org_unit_id": str(ou.org_unit_id), "name": ou.name},
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.updated: {_oe}")

        logger.info(f"Updated org unit: {ou.org_unit_id}")

        return {
            "org_unit_id": str(ou.org_unit_id),
            "tenant_id": str(ou.tenant_id),
            "name": ou.name,
            "type": ou.type,
            "status": ou.status,
            "updated_at": ou.updated_at.isoformat() if ou.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Update org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/org_units/{org_unit_id}/deactivate")
async def deactivate_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.update")),
):
    """Archive an org unit. Keeps assignments + role scopes; hidden from dropdowns."""
    try:
        ou_id = uuid.UUID(org_unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

    ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
    if not ou:
        raise HTTPException(status_code=404, detail="Org unit not found")

    if ou.status == "archived":
        return {"org_unit_id": org_unit_id, "status": "archived", "affected_users": 0}

    # Count live references so the frontend can warn ("12 users will lose this department")
    affected_users = db.query(UserOrgAssignment).filter(
        UserOrgAssignment.org_unit_id == ou_id,
    ).count()

    ou.status = "archived"
    ou.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, ou.tenant_id, "org_unit.deactivated",
                            {"org_unit_id": org_unit_id, "affected_users": affected_users})
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for org_unit.deactivated: {_oe}")

    logger.info(f"Archived org unit: {org_unit_id} ({affected_users} user assignments kept)")
    return {"org_unit_id": org_unit_id, "status": "archived", "affected_users": affected_users}


@router.post("/org_units/{org_unit_id}/activate")
async def activate_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.update")),
):
    """Restore an archived org unit to active."""
    try:
        ou_id = uuid.UUID(org_unit_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

    ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
    if not ou:
        raise HTTPException(status_code=404, detail="Org unit not found")

    if ou.status == "active":
        return {"org_unit_id": org_unit_id, "status": "active"}

    ou.status = "active"
    ou.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        create_outbox_event(db, ou.tenant_id, "org_unit.activated", {"org_unit_id": org_unit_id})
        db.commit()
    except Exception as _oe:
        logger.warning(f"Outbox event failed for org_unit.activated: {_oe}")

    logger.info(f"Reactivated org unit: {org_unit_id}")
    return {"org_unit_id": org_unit_id, "status": "active"}


@router.delete("/org_units/{org_unit_id}", status_code=200)
async def delete_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.delete", resource_from="none")),
):
    """
    Soft delete by default: active units get archived (assignments + scopes kept).

    Hard delete only when the unit is already archived AND has zero references
    (no children, no user assignments, no role scopes, no range mappings).
    """
    try:
        try:
            ou_id = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # ── Soft path: archive active units ───────────────────────
        if ou.status != "archived":
            affected_users = db.query(UserOrgAssignment).filter(
                UserOrgAssignment.org_unit_id == ou_id,
            ).count()
            ou.status = "archived"
            ou.updated_at = datetime.now(timezone.utc)
            db.commit()
            try:
                create_outbox_event(db, ou.tenant_id, "org_unit.deactivated",
                                    {"org_unit_id": org_unit_id, "affected_users": affected_users, "via": "delete"})
                db.commit()
            except Exception as _oe:
                logger.warning(f"Outbox event failed for org_unit.deactivated: {_oe}")
            logger.info(f"Soft-deleted (archived) org unit: {org_unit_id}")
            return {"org_unit_id": org_unit_id, "status": "archived", "deleted": False,
                    "affected_users": affected_users}

        # ── Hard path: archived + zero references ─────────────────
        children_count = db.query(OrgUnit).filter(OrgUnit.parent_org_unit_id == ou_id).count()
        assignment_count = db.query(UserOrgAssignment).filter(UserOrgAssignment.org_unit_id == ou_id).count()
        home_count = db.query(User).filter(User.home_org_unit_id == ou_id).count()
        role_scope_count = db.query(TenantRoleScope).filter(
            TenantRoleScope.scope_type == "department",
            TenantRoleScope.scope_id == ou_id,
        ).count()
        range_count = db.query(ApprovedRangeOrgUnit).filter(
            ApprovedRangeOrgUnit.org_unit_id == ou_id,
        ).count()

        blockers = {
            "child_units": children_count,
            "user_assignments": assignment_count,
            "home_org_unit_users": home_count,
            "role_scopes": role_scope_count,
            "approved_range_mappings": range_count,
        }
        blockers = {k: v for k, v in blockers.items() if v > 0}
        if blockers:
            raise HTTPException(
                status_code=400,
                detail=f"Org unit is archived but still referenced: {blockers}. Remove references before hard delete.",
            )

        _tid = ou.tenant_id
        db.delete(ou)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, _tid, "org_unit.deleted", {"org_unit_id": org_unit_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.deleted: {_oe}")

        logger.info(f"Hard-deleted org unit: {org_unit_id}")
        return {"org_unit_id": org_unit_id, "status": "deleted", "deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Delete org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# =============================================================================
# ORG UNIT - USER ASSIGNMENT ENDPOINTS
# =============================================================================

@router.post("/org_units/assignments", status_code=201)
async def assign_user_to_org_unit(
        req: OrgUnitAssignmentRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.assign")),
        policy=Depends(require_policy("org_unit.assign_user")),
):
    """
    Assign a user to an organisational unit with a specific role.

    This creates a mapping between a user and an org unit, defining their
    role within that organisational structure.
    """
    try:
        # Validate UUIDs
        try:
            user_uuid = uuid.UUID(req.user_id)
            org_unit_uuid = uuid.UUID(req.org_unit_id)
            role_uuid = uuid.UUID(req.role_id)
            assigned_by_uuid = uuid.UUID(req.assigned_by) if req.assigned_by else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid UUID format: {e}")

        # Verify user exists
        user = db.query(User).filter(User.user_id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify org unit exists and belongs to same tenant
        org_unit = db.query(OrgUnit).filter(
            OrgUnit.org_unit_id == org_unit_uuid,
            OrgUnit.tenant_id == user.tenant_id
        ).first()
        if not org_unit:
            raise HTTPException(status_code=404, detail="Org unit not found or does not belong to user's tenant")

        # Verify role exists
        role = db.query(Role).filter(Role.role_id == role_uuid).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # Check if assignment already exists
        existing = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == user_uuid,
            UserOrgAssignment.org_unit_id == org_unit_uuid
        ).first()

        if existing:
            # Update existing assignment with new role
            existing.role_id = role_uuid
            existing.assigned_by = assigned_by_uuid
            existing.assigned_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)

            logger.info(f"Updated user {user_uuid} assignment to org unit {org_unit_uuid} with role {role_uuid}")

            return {
                "assignment_id": str(existing.assignment_id),
                "user_id": str(existing.user_id),
                "org_unit_id": str(existing.org_unit_id),
                "role_id": str(existing.role_id),
                "role_code": role.code,
                "assigned_by": str(existing.assigned_by) if existing.assigned_by else None,
                "assigned_at": existing.assigned_at.isoformat() if existing.assigned_at else None,
                "message": "Assignment updated"
            }

        # Create new assignment
        assignment = UserOrgAssignment(
            user_id=user_uuid,
            org_unit_id=org_unit_uuid,
            role_id=role_uuid,
            assigned_by=assigned_by_uuid
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

        # Outbox audit event
        try:
            create_outbox_event(
                db, user.tenant_id, "org_unit_assignment.created",
                {
                    "user_id": req.user_id,
                    "org_unit_id": req.org_unit_id,
                    "role_id": req.role_id,
                },
            )
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit_assignment.created: {_oe}")

        logger.info(f"Assigned user {user_uuid} to org unit {org_unit_uuid} with role {role_uuid}")

        return {
            "assignment_id": str(assignment.assignment_id),
            "user_id": str(assignment.user_id),
            "org_unit_id": str(assignment.org_unit_id),
            "role_id": str(assignment.role_id),
            "role_code": role.code,
            "assigned_by": str(assignment.assigned_by) if assignment.assigned_by else None,
            "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
            "message": "Assignment created"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Assign user to org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/org_units/{org_unit_id}/users")
async def get_org_unit_users(
        org_unit_id: str,
        include_children: bool = Query(False, description="Include users from child org units"),
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage"))
):
    """
    Get all users assigned to an organisational unit.

    Optionally include users from child org units.
    """
    try:
        try:
            ou_uuid = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        # Verify org unit exists
        org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_uuid).first()
        if not org_unit:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # Get org unit IDs to query
        org_unit_ids = [ou_uuid]

        if include_children:
            # Get all child org units recursively
            def get_children_ids(parent_id):
                children = db.query(OrgUnit.org_unit_id).filter(
                    OrgUnit.parent_org_unit_id == parent_id
                ).all()
                child_ids = [c[0] for c in children]
                for child_id in child_ids:
                    child_ids.extend(get_children_ids(child_id))
                return child_ids

            org_unit_ids.extend(get_children_ids(ou_uuid))

        # Query assignments with user and role info
        assignments = db.query(
            UserOrgAssignment,
            User,
            Role,
            OrgUnit
        ).join(
            User, UserOrgAssignment.user_id == User.user_id
        ).join(
            Role, UserOrgAssignment.role_id == Role.role_id
        ).join(
            OrgUnit, UserOrgAssignment.org_unit_id == OrgUnit.org_unit_id
        ).filter(
            UserOrgAssignment.org_unit_id.in_(org_unit_ids)
        ).all()

        users = []
        from provisioning_service.Models import UserIdentity
        for assignment, user, role, ou in assignments:
            identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
            users.append({
                "assignment_id": str(assignment.assignment_id),
                "user_id": str(user.user_id),
                "email": identity.email if identity else None,
                "first_name": identity.first_name if identity else None,
                "last_name": identity.last_name if identity else None,
                "display_name": user.display_name,
                "position": user.position,
                "is_active": user.is_active,
                "org_unit_id": str(ou.org_unit_id),
                "org_unit_name": ou.name,
                "role_id": str(role.role_id),
                "role_code": role.code,
                "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None
            })

        return {
            "org_unit_id": str(org_unit.org_unit_id),
            "org_unit_name": org_unit.name,
            "include_children": include_children,
            "total_users": len(users),
            "users": users
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get org unit users failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/users/{user_id}/org_units")
async def get_user_org_units(
        user_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage"))
):
    """
    Get all organisational units a user is assigned to.
    """
    try:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id format")

        # Verify user exists
        user = db.query(User).filter(User.user_id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Query assignments
        assignments = db.query(
            UserOrgAssignment,
            OrgUnit,
            Role
        ).join(
            OrgUnit, UserOrgAssignment.org_unit_id == OrgUnit.org_unit_id
        ).join(
            Role, UserOrgAssignment.role_id == Role.role_id
        ).filter(
            UserOrgAssignment.user_id == user_uuid
        ).all()

        org_units = []
        for assignment, ou, role in assignments:
            org_units.append({
                "assignment_id": str(assignment.assignment_id),
                "org_unit_id": str(ou.org_unit_id),
                "org_unit_name": ou.name,
                "org_unit_type": ou.type,
                "org_unit_status": ou.status,
                "role_id": str(role.role_id),
                "role_code": role.code,
                "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None
            })

        from provisioning_service.Models import UserIdentity
        identity = db.query(UserIdentity).filter(UserIdentity.user_id == user.user_id).first()
        return {
            "user_id": str(user.user_id),
            "email": identity.email if identity else None,
            "first_name": identity.first_name if identity else None,
            "last_name": identity.last_name if identity else None,
            "total_assignments": len(org_units),
            "org_units": org_units
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user org units failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/org_units/assignments/{assignment_id}", status_code=204)
async def remove_user_from_org_unit(
        assignment_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.assign")),
        policy=Depends(require_policy("org_unit.remove_user", resource_from="none")),
):
    """
    Remove a user's assignment from an organisational unit.
    """
    try:
        try:
            assignment_uuid = uuid.UUID(assignment_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid assignment_id format")

        assignment = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.assignment_id == assignment_uuid
        ).first()

        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        user_id = assignment.user_id
        org_unit_id = assignment.org_unit_id

        db.delete(assignment)
        db.commit()

        logger.info(f"Removed user {user_id} from org unit {org_unit_id}")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Remove user from org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/org_units/{org_unit_id}/users/{user_id}", status_code=204)
async def remove_user_from_org_unit_by_ids(
        org_unit_id: str,
        user_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.assign")),
        policy=Depends(require_policy("org_unit.remove_user", resource_from="none")),
):
    """
    Remove a user's assignment from an organisational unit by org_unit_id and user_id.
    """
    try:
        try:
            ou_uuid = uuid.UUID(org_unit_id)
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid UUID format")

        assignment = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.org_unit_id == ou_uuid,
            UserOrgAssignment.user_id == user_uuid
        ).first()

        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        db.delete(assignment)
        db.commit()

        logger.info(f"Removed user {user_id} from org unit {org_unit_id}")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Remove user from org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

