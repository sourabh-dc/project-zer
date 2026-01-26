import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional
import secrets
import bcrypt
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import  Response

from provisioning_service.Models import Tenant, Role, User, Vendor, Site, Store, CostCentre, UserCostCentre, \
    SpendingEvent, SiteTenant, \
    OrgUnit, UserOrgAssignment, UserRole, RolePermission, Permission, TenantRole, TenantRolePermission, TenantUserRole, \
    CostCenterBudget, VendorUser
from provisioning_service.Schemas import UserContext, SiteRequest, StoreRequest, UserRequest, BulkUserRequest, \
    CostCentreRequest, VendorRequest, OrgUnitRequest, OrgUnitAssignmentRequest, PasswordResetRequest, AssignRoleRequest, \
    RoleRequest, TenantUpdateRequest, TenantRoleRequest, TenantRolePermissionRequest, TenantRoleAssignRequest, \
    VendorUserCreate, VendorUserUpdate
from provisioning_service.core.config import SETTINGS
from provisioning_service.core.db_config import get_db
from provisioning_service.core.helpers.aifi_services import cv_create_customer
from provisioning_service.core.permission_check_helpers import check_tenant_access
from provisioning_service.core.user_auth import generate_api_key, invalidate_user_context, check_user_authorization
from provisioning_service.core.entitlement_helpers import check_feature_limit, record_feature_usage
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
        db: Session = Depends(get_db)
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


@router.post("/sites", status_code=201)
async def create_site(
        req: SiteRequest,
        db: Session = Depends(get_db),
        # ctx = Depends(check_user_authorization("sites.manage"))
):
    """Create a new site and associate it with a tenant"""
    try:
        # Check entitlement limit
        check_feature_limit(db, req.tenant_id, "sites.manage", count=1)
        
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
    user = Depends(check_user_authorization('tenant.admin'))
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
    db: Session = Depends(get_db)
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

@router.post("/stores", status_code=201)
async def create_store(
        req: StoreRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("stores.manage"))
):
    """Create a new store under a site for the user's tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()
        
        # Check entitlement limit
        check_feature_limit(db, req.tenant_id, "stores.manage", count=1)
        
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
    name: Optional[str] = Query(None, description="New store name"),
    store_type: Optional[str] = Query(None, description="New store type"),
    geo: Optional[str] = Query(None, description="New geo location"),
    db: Session = Depends(get_db)
):
    """Update store information"""
    start = datetime.now()
    try:
        req_total.labels(operation="update_store", status="start").inc()

        # Find store
        store = db.query(Store).filter(Store.store_id == uuid.UUID(store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")

        # Update fields if provided
        updated = False
        if name is not None:
            store.name = name
            updated = True
        if store_type is not None:
            store.store_type = store_type
            updated = True
        if geo is not None:
            store.geo = geo
            updated = True

        if not updated:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        store.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(store)

        req_total.labels(operation="update_store", status="success").inc()
        req_duration.labels(operation="update_store").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Updated store: {store.store_id} ({store.name})")

        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id),
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "geo": store.geo,
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


@router.post("/users", status_code=201)
async def create_user(
        req: UserRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("users.manage"))
):
    """Create a new user"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_user", status="start").inc()
        
        # Check entitlement limit
        check_feature_limit(db, req.tenant_id, "users.manage", count=1)

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

        # Create user
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

        try:
            aifi_customer = await cv_create_customer(
                {"externalId": user.user_id, "email": user.email, "firstName": user.first_name,
                 "lastName": user.last_name})
            user.aifi_customer_id = aifi_customer.get("id")
            db.commit()
        except Exception as e:
            logger.warning(f"❌ AiFi customer sync failed, continuing: {e}")
            db.rollback()
        # Record feature usage
        record_feature_usage(db, req.tenant_id, "users.manage", count=1)

        req_total.labels(operation="create_user", status="success").inc()
        req_duration.labels(operation="create_user").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"Created user: {user.user_id} ({user.email})")

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


@router.post("/users/bulk-import", status_code=201)
async def bulk_import_users(
        req: BulkUserRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(check_user_authorization('tenant.admin')
        )
):
    """Bulk import users"""
    start = datetime.now()
    try:
        req_total.labels(operation="bulk_import_users", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        results = {"success": [], "failed": []}
        tenant_uuid = uuid.UUID(req.tenant_id)

        for user_data in req.users:
            try:
                email = user_data.get("email")
                display_name = user_data.get("display_name", email)

                if not email:
                    results["failed"].append({"error": "Missing email", "data": user_data})
                    continue

                # Check if email exists
                if db.query(User).filter(func.lower(User.email) == email.lower()).first():
                    results["failed"].append({"email": email, "error": "Email already exists"})
                    continue

                # Generate random password
                temp_password = f"temp_{secrets.token_urlsafe(16)}"
                password_hash = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                # Generate API key
                api_key = generate_api_key()
                api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)

                # Create user
                user = User(
                    user_id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    email=email.lower(),
                    display_name=display_name,
                    password=password_hash,
                    active=True
                )
                db.add(user)
                db.flush()

                results["success"].append({
                    "user_id": str(user.user_id),
                    "email": email,
                    "api_key": api_key,
                    "temporary_password": temp_password
                })
            except Exception as e:
                results["failed"].append({"email": user_data.get("email", "unknown"), "error": str(e)})

        db.commit()

        req_total.labels(operation="bulk_import_users", status="success").inc()
        req_duration.labels(operation="bulk_import_users").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Bulk import: {len(results['success'])}/{len(req.users)} succeeded")

        return {
            "tenant_id": req.tenant_id,
            "total_requested": len(req.users),
            "success_count": len(results["success"]),
            "failed_count": len(results["failed"]),
            "results": results
        }
    except HTTPException:
        req_total.labels(operation="bulk_import_users", status="error").inc()
        raise
    except Exception as e:
        db.rollback()
        req_total.labels(operation="bulk_import_users", status="error").inc()
        logger.error(f"❌ Bulk import failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/vendors", status_code=201)
async def create_vendor(
        req: VendorRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("vendors.manage"))
):
    """Create a new vendor"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_vendor", status="start").inc()
        
        # Check entitlement limit
        check_feature_limit(db, req.tenant_id, "vendors.manage", count=1)

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
def create_vendor_user(payload: VendorUserCreate, db: Session = Depends(get_db)):
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
def update_vendor_user(user_id: uuid.UUID, payload: VendorUserUpdate, db: Session = Depends(get_db)):
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
def delete_vendor_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
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

@router.post("/cost-centres", status_code=201)
async def create_cost_centre(
        req: CostCentreRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("costcentre.manage"))
):
    """Create a new cost centre"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()

        # Check entitlement limit (feature). If feature not in plan, this will raise.
        try:
            check_feature_limit(db, req.tenant_id, "cost_centres", count=1)
        except HTTPException:
            raise

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
    db: Session = Depends(get_db)
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
    ctx = Depends(check_user_authorization("budgets.manage"))
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
        db: Session = Depends(get_db)
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
        db: Session = Depends(get_db)
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
        db: Session = Depends(get_db)
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
    ctx = Depends(check_user_authorization("tenant.admin"))
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
    ctx = Depends(check_user_authorization("tenant.admin"))
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
    ctx = Depends(check_user_authorization("users.manage"))
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
        db: Session = Depends(get_db)
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

        req_total.labels(operation="assign_role", status="success").inc()
        req_duration.labels(operation="assign_role").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Assigned role {req.role_id} to user {user_id}")
        invalidate_user_context(str(user.user_id), str(user.tenant_id))

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
        db: Session = Depends(get_db)
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

        req_total.labels(operation="remove_role", status="success").inc()
        req_duration.labels(operation="remove_role").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Removed role {role_id} from user {user_id}")
        if user:
            invalidate_user_context(str(user.user_id), str(user.tenant_id))

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


@router.post("/org_units", status_code=201)
async def create_org_unit(
        req: OrgUnitRequest,
        db: Session = Depends(get_db),
        ctx = Depends(check_user_authorization("org_units.manage"))
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
        ctx = Depends(check_user_authorization("org_units.manage"))
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
        ctx = Depends(check_user_authorization("org_units.manage"))
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
        db.delete(ou)
        db.commit()

        logger.info(f"Deleted org unit: {org_unit_id}")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Delete org unit failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

