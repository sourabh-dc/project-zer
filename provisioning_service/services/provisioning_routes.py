import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional
import bcrypt
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, Role, User, Vendor, Site, Store, CostCentre, UserCostCentre, \
    SpendingEvent, SiteTenant, \
    OrgUnit, UserOrgAssignment, UserRole, RolePermission, Permission, TenantRole, TenantRolePermission, TenantUserRole, \
    CostCenterBudget, VendorUser
from provisioning_service.Schemas import UserContext, SiteRequest, StoreRequest, UserRequest, BulkUserRequest, \
    CostCentreRequest, VendorRequest, OrgUnitRequest, OrgUnitAssignmentRequest, AssignRoleRequest, \
    RoleRequest, TenantUpdateRequest, TenantRoleRequest, TenantRolePermissionRequest, TenantRoleAssignRequest, \
    VendorUserCreate, VendorUserUpdate, \
    SiteUpdateRequest, StoreUpdateRequest, UserUpdateRequest, VendorUpdateRequest, CostCentreUpdateRequest

from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.entitlement_helpers import record_feature_usage
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
        record_feature_usage(db, req.tenant_id, "sites.manage", count=1)

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
        record_feature_usage(db, req.tenant_id, "stores.manage", count=1)

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


@router.post("/users", status_code=201)
async def create_user(
        req: UserRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("users.manage")),
        policy=Depends(require_policy("user.create", resource_loader=user_quota_resource)),
):
    """Create a new user"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_user", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Check if email exists
        existing = db.query(User).filter(func.lower(User.email) == req.email.lower()).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")

        # Hash password
        password_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Create user (persist user record immediately)
        user = User(
            user_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            email=req.email,
            password_hash=password_hash,
            first_name=req.first_name,
            last_name=req.last_name,
            display_name=f"{req.first_name} {req.last_name}",
            phone=getattr(req, "phone", None),
            is_active=True,
            position=getattr(req, "position", None),
            profile_image=getattr(req, "profile_image", None),
            is_sso_enabled=bool(getattr(req, "is_sso_enabled", False)),
            home_site_id=uuid.UUID(req.home_site_id) if getattr(req, "home_site_id", None) else None,
            home_store_id=uuid.UUID(req.home_store_id) if getattr(req, "home_store_id", None) else None,
            home_org_unit_id=uuid.UUID(req.home_org_unit_id) if getattr(req, "home_org_unit_id", None) else None,
            all_locations=bool(getattr(req, "all_locations", False))
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        # Create outbox event for post-create processing (e.g., aiFi sync) and send outbox_id to queue
        event_data = {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name
        }
        outbox = create_outbox_event(db, user.tenant_id, "user.created", event_data, status="pending")
        db.commit()

        try:
            from provisioning_service.core.sb_client import messaging_service
            await messaging_service.send_outbox_message(str(outbox.id))
        except Exception as e:
            # The outbox worker will pick this up later if the notify fails.
            logger.warning(f"Failed to notify Service Bus: {e}")

        # Record feature usage
        record_feature_usage(db, req.tenant_id, "users.manage", count=1)

        req_total.labels(operation="create_user", status="success").inc()
        req_duration.labels(operation="create_user").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"Created user: {user.user_id} ({user.email}) - outbox {outbox.id}")

        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_user", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        raise HTTPException(status_code=409, detail="Email already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_user", status="error").inc()
        logger.error(f"User creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    try:
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": user.display_name,
            "phone": user.phone,
            "position": user.position,
            "profile_image": user.profile_image,
            "is_sso_enabled": user.is_sso_enabled,
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
        if "first_name" in update_data or "last_name" in update_data:
            user.display_name = f"{user.first_name} {user.last_name}"

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

        logger.info(f"✅ Updated user: {user.user_id}")
        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
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
        record_feature_usage(db, req.tenant_id, "vendors.manage", count=1)

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
        record_feature_usage(db, req.tenant_id, "cost_centres", count=1)

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
    """Get all permissions for a role"""
    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_code == Permission.code
    ).filter(
        RolePermission.role_code == role_code
    ).all()

    return {
        "role_code": role_code,
        "permissions": [
            {
                "permission_code": str(p.permission_code),
                "code": p.code,
                "description": p.description
            }
            for rp, p in role_perms
        ]
    }


# Tenant-scoped roles (custom per tenant; permissions remain global)
@router.post("/tenant-roles", status_code=201)
async def create_tenant_role(
    req: TenantRoleRequest,
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin")),
    policy=Depends(require_policy("tenant_role.create")),
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant context")
    existing = db.query(TenantRole).filter(
        TenantRole.tenant_id == uuid.UUID(str(tenant_id)),
        TenantRole.code == req.code
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Role code already exists for this tenant")
    role = TenantRole(
        role_id=uuid.uuid4(),
        tenant_id=uuid.UUID(str(tenant_id)),
        code=req.code,
        description=req.description
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return {"role_id": str(role.role_id), "code": role.code, "description": role.description}


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
    db: Session = Depends(get_db),
    ctx = Depends(check_user_authorization("tenant.admin"))
):
    tenant_id = ctx.get("tenant_id") if isinstance(ctx, dict) else getattr(ctx, "tenant_id", None)
    roles = db.query(TenantRole).filter(TenantRole.tenant_id == uuid.UUID(str(tenant_id))).all()
    return {
        "roles": [
            {"role_id": str(r.role_id), "code": r.code, "description": r.description}
            for r in roles
        ]
    }

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
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get user roles
        user_roles = (
            db.query(UserRole, Role)
            .join(Role, UserRole.role_id == Role.role_id)
            .filter(UserRole.user_id == uuid.UUID(user_id))
            .all()
        )

        return {
            "user_id": user_id,
            "email": user.email,
            "display_name": user.display_name,
            "roles": [
                {
                    "role_id": str(r.role_id),
                    "role_code": r.code,
                    "role_name": r.code,
                    "assigned_at": ur.created_at.isoformat()
                }
                for ur, r in user_roles
            ],
            "total": len(user_roles)
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

        # Find user role assignment
        user_role = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(role_id)
        ).first()

        if not user_role:
            raise HTTPException(status_code=404, detail="Role assignment not found")

        user = db.query(User).filter(User.user_id == user_role.user_id).first()
        db.delete(user_role)
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


@router.delete("/org_units/{org_unit_id}", status_code=204)
async def delete_org_unit(
        org_unit_id: str,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage")),
        policy=Depends(require_policy("org_unit.delete", resource_from="none")),
):
    """Delete an organisational unit (soft delete by default)"""
    try:
        try:
            ou_id = uuid.UUID(org_unit_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid org_unit_id format")

        ou = db.query(OrgUnit).filter(OrgUnit.org_unit_id == ou_id).first()
        if not ou:
            raise HTTPException(status_code=404, detail="Org unit not found")

        # If children exist, prevent delete unless forced - simple safety
        children_count = db.query(OrgUnit).filter(OrgUnit.parent_org_unit_id == ou_id).count()
        if children_count > 0:
            raise HTTPException(status_code=400, detail="Org unit has child units; remove or reparent before delete")

        # Perform delete (hard delete here - cascade will handle relations)
        _tid = ou.tenant_id
        db.delete(ou)
        db.commit()

        # Outbox audit event
        try:
            create_outbox_event(db, _tid, "org_unit.deleted", {"org_unit_id": org_unit_id})
            db.commit()
        except Exception as _oe:
            logger.warning(f"Outbox event failed for org_unit.deleted: {_oe}")

        logger.info(f"Deleted org unit: {org_unit_id}")
        return Response(status_code=204)
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
        for assignment, user, role, ou in assignments:
            users.append({
                "assignment_id": str(assignment.assignment_id),
                "user_id": str(user.user_id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
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

        return {
            "user_id": str(user.user_id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
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

