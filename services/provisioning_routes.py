import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, APIRouter, HTTPException, Query
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text, func, Index
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from Models import Tenant, Role, UserRole, User, Vendor, Site, Store, CostCentre, Permission, RolePermission, RoleScope, \
    UserCostCentre, SpendingEvent, SiteTenant, OrgUnit, UserOrgAssignment
from Schemas import TenantRequest, UserContext, SiteRequest, StoreRequest, UserRequest, BulkUserRequest, \
    AssignRoleRequest, RoleRequest, CostCentreRequest, VendorRequest, SuperUserRequest, OrgUnitRequest, \
    OrgUnitAssignmentRequest, PasswordResetRequest
from core.config import SERVICE_NAME, SERVICE_VERSION, SETTINGS
from core.db_config import SessionLocal, get_db
from core.permission_check_helpers import require_permission, check_tenant_access
from core.user_auth import generate_api_key, invalidate_user_context
from utils.logger import logger
from utils.metrics import req_total, req_duration
from utils.redis_client import redis_client


app = APIRouter()

"""
ZeroQue Provisioning Service - Simplified Production Version

A clean, powerful API for multi-tenant provisioning with PostgreSQL RLS.
"""
# ==================================================================================
# API ENDPOINTS
# ==================================================================================
@app.post("/v1/tenants", status_code=201)
async def create_tenant(
        req: TenantRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("tenants.create"))
):
    """Create a new tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_tenant", status="start").inc()

        # Check if tenant exists
        existing = db.query(Tenant).filter(Tenant.name == req.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="Tenant name already exists")

        # Create tenant
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            name=req.name,
            tenant_type=req.type,
            active=True
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        req_total.labels(operation="create_tenant", status="success").inc()
        req_duration.labels(operation="create_tenant").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created tenant: {tenant.tenant_id} ({tenant.name})")

        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
            "type": tenant.tenant_type,
            "created_at": tenant.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_tenant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        raise HTTPException(status_code=409, detail="Tenant already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_tenant", status="error").inc()
        logger.error(f"❌ Tenant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/tenants/{tenant_id}/super-user", status_code=201)
async def create_tenant_super_user(
        tenant_id: str,
        req: SuperUserRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("tenants.create"))
):
    """Create a super user for a tenant with all permissions"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_super_user", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Check if email exists
        existing = db.query(User).filter(func.lower(User.email) == req.email.lower()).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")

        # Generate password if not provided
        password = req.password
        if not password:
            password = secrets.token_urlsafe(16)
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Generate API key
        api_key = generate_api_key()
        api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)

        # Create user
        user = User(
            user_id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id),
            email=req.email.lower(),
            display_name=req.display_name,
            password_hash=password_hash,
            active=True,
            api_key=api_key,
            api_key_created_at=datetime.now(timezone.utc),
            api_key_expires_at=api_key_expires_at
        )
        db.add(user)
        db.flush()  # Get user_id

        # Create or get "tenant_admin" role
        admin_role = db.query(Role).filter(Role.code == "tenant_admin").first()
        if not admin_role:
            admin_role = Role(
                role_id=uuid.uuid4(),
                code="tenant_admin",
                description="Tenant administrator with full permissions"
            )
            db.add(admin_role)
            db.flush()

        # Get all permissions
        all_permissions = db.query(Permission).all()
        
        # Assign all permissions to tenant_admin role
        for perm in all_permissions:
            existing_rp = db.query(RolePermission).filter(
                RolePermission.role_id == admin_role.role_id,
                RolePermission.permission_id == perm.permission_id
            ).first()
            if not existing_rp:
                rp = RolePermission(
                    id=uuid.uuid4(),
                    role_id=admin_role.role_id,
                    permission_id=perm.permission_id
                )
                db.add(rp)

        # Add tenant-level scope to role (allows access to all resources in tenant)
        existing_scope = db.query(RoleScope).filter(
            RoleScope.role_id == admin_role.role_id,
            RoleScope.resource_type == "tenant",
            RoleScope.resource_id == uuid.UUID(tenant_id)
        ).first()
        
        if not existing_scope:
            scope = RoleScope(
                id=uuid.uuid4(),
                role_id=admin_role.role_id,
                resource_type="tenant",
                resource_id=uuid.UUID(tenant_id),
                grant_type="include"
            )
            db.add(scope)

        # Assign role to user
        user_role = UserRole(
            id=uuid.uuid4(),
            user_id=user.user_id,
            role_id=admin_role.role_id
        )
        db.add(user_role)
        db.commit()
        db.refresh(user)

        req_total.labels(operation="create_super_user", status="success").inc()
        req_duration.labels(operation="create_super_user").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created super user: {user.user_id} ({user.email}) for tenant: {tenant_id}")
        invalidate_user_context(str(user.user_id), str(user.tenant_id))

        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "display_name": user.display_name,
            "api_key": api_key,
            "api_key_expires_at": api_key_expires_at.isoformat(),
            "password": password if not req.password else None,  # Only return if auto-generated
            "role_assigned": "tenant_admin",
            "created_at": user.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_super_user", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except HTTPException:
        req_total.labels(operation="create_super_user", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_super_user", status="error").inc()
        raise HTTPException(status_code=409, detail="Email already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_super_user", status="error").inc()
        logger.error(f"❌ Super user creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/tenants")
async def list_tenants(
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(require_permission("tenants.create"))
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
                "name": t.name,
                "type": t.tenant_type,
                "created_at": t.created_at.isoformat()
            }
            for t in tenants
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@app.get("/v1/tenants/{tenant_id}")
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
            "name": tenant.name,
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


@app.put("/v1/tenants/{tenant_id}")
async def update_tenant(
        tenant_id: str,
        name: Optional[str] = Query(None, description="New tenant name"),
        db: Session = Depends(get_db)
):
    """Update a tenant's information"""
    start = datetime.now()
    try:
        req_total.labels(operation="update_tenant", status="start").inc()

        # Find tenant
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Update fields
        if name:
            # Check if new name conflicts
            existing = db.query(Tenant).filter(
                Tenant.name == name,
                Tenant.tenant_id != uuid.UUID(tenant_id)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="Tenant name already exists")
            tenant.name = name

        tenant.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(tenant)

        # Clear cache
        if redis_client:
            try:
                redis_client.delete(f"tenant:{tenant_id}")
            except Exception as e:
                logger.warning(f"Cache clear failed: {e}")

        req_total.labels(operation="update_tenant", status="success").inc()
        req_duration.labels(operation="update_tenant").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Updated tenant: {tenant.tenant_id}")

        return {
            "tenant_id": str(tenant.tenant_id),
            "name": tenant.name,
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


@app.post("/v1/sites", status_code=201)
async def create_site(
        req: SiteRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("sites.manage"))
):
    """Create a new site and associate it with a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_site", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Create site (no tenant_id here)
        site = Site(
            site_id=uuid.uuid4(),
            name=req.name,
            site_type=req.type,
            geo=req.geo
        )
        db.add(site)
        db.flush()  # Get site_id
        
        # Create site-tenant relationship
        site_tenant = SiteTenant(
            id=uuid.uuid4(),
            site_id=site.site_id,
            tenant_id=uuid.UUID(req.tenant_id)
        )
        db.add(site_tenant)
        db.commit()
        db.refresh(site)

        req_total.labels(operation="create_site", status="success").inc()
        req_duration.labels(operation="create_site").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created site: {site.site_id} ({site.name}) for tenant: {req.tenant_id}")

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
        logger.error(f"❌ Site creation IntegrityError: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid tenant reference: {str(e)}")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"❌ Site creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/v1/sites/{site_id}/tenants/{tenant_id}", status_code=201)
async def add_tenant_to_site(
    site_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage"))
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
        
        # Check if association already exists
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

@app.get("/v1/sites/{site_id}/tenants")
async def list_site_tenants(
    site_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage"))
):
    """List all tenants associated with a site"""
    try:
        # Verify site exists and is accessible by user's tenant
        site_access = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(site_id),
            SiteTenant.tenant_id == ctx.tenant_id
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
                    "name": t.name,
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

@app.delete("/v1/sites/{site_id}/tenants/{tenant_id}", status_code=204)
async def remove_tenant_from_site(
    site_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage"))
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
        
@app.get("/v1/sites")
async def list_sites(
        tenant_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("sites.manage"))
):
    """List sites with optional tenant filtering"""
    try:
        # Start with SiteTenant join to support many-to-many
        q = db.query(Site).join(SiteTenant, Site.site_id == SiteTenant.site_id)
        
        # If tenant_id provided, filter by it; otherwise filter by user's tenant
        if tenant_id:
            q = q.filter(SiteTenant.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(SiteTenant.tenant_id == ctx.tenant_id)

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

@app.post("/v1/stores", status_code=201)
async def create_store(
        req: StoreRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.manage"))
):
    """Create a new store under a site for the user's tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()
        print(ctx)
        # Verify site exists and is accessible by user's tenant
        site_tenant = db.query(SiteTenant).filter(
            SiteTenant.site_id == uuid.UUID(req.site_id),
            SiteTenant.tenant_id == ctx.tenant_id  # Use user's tenant from context
        ).first()
        
        if not site_tenant:
            raise HTTPException(
                status_code=404, 
                detail="Site not found or not accessible by your tenant"
            )

        # Create store
        store = Store(
            store_id=uuid.uuid4(),
            site_id=uuid.UUID(req.site_id),
            tenant_id=ctx.tenant_id,  # Use user's tenant
            name=req.name,
            store_type=req.type,
            geo=req.geo
        )
        db.add(store)
        db.commit()
        db.refresh(store)

        req_total.labels(operation="create_store", status="success").inc()
        req_duration.labels(operation="create_store").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created store: {store.store_id} ({store.name}) for tenant: {ctx.tenant_id}")

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
        logger.error(f"❌ Store creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/stores")
async def list_stores(
        site_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.manage"))
):
    """List stores with optional site filtering"""
    try:
        q = db.query(Store).filter(Store.tenant_id == ctx.tenant_id)  # Always filter by user's tenant
        
        if site_id:
            # Verify site access before filtering stores
            site_access = db.query(SiteTenant).filter(
                SiteTenant.site_id == uuid.UUID(site_id),
                SiteTenant.tenant_id == ctx.tenant_id
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


@app.post("/v1/users", status_code=201)
async def create_user(
        req: UserRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "users.manage",
                None
            )
        )
):
    """Create a new user"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_user", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

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

        # Generate API key
        api_key = generate_api_key()
        api_key_expires_at = datetime.now(timezone.utc) + timedelta(days=SETTINGS.API_KEY_EXPIRY_DAYS)

        # Create user
        user = User(
            user_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            email=req.email.lower(),
            display_name=req.display_name,
            password_hash=password_hash,
            active=True,
            api_key=api_key,
            api_key_created_at=datetime.now(timezone.utc),
            api_key_expires_at=api_key_expires_at
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        req_total.labels(operation="create_user", status="success").inc()
        req_duration.labels(operation="create_user").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created user: {user.user_id} ({user.email})")

        return {
            "user_id": str(user.user_id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "display_name": user.display_name,
            "api_key": api_key,
            "api_key_expires_at": api_key_expires_at.isoformat(),
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
        logger.error(f"❌ User creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users")
async def list_users(
        tenant_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("users.manage"))
):
    """List users with optional tenant filtering"""
    try:
        q = db.query(User).filter(User.active == True)
        if tenant_id:
            q = q.filter(User.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(User.tenant_id == ctx.tenant_id)  # Filter by user's tenant by default

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


@app.post("/v1/users/bulk-import", status_code=201)
async def bulk_import_users(
        req: BulkUserRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "users.manage",
                None
            )
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
                    password_hash=password_hash,
                    active=True,
                    api_key=api_key,
                    api_key_created_at=datetime.now(timezone.utc),
                    api_key_expires_at=api_key_expires_at
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


@app.post("/v1/roles", status_code=201)
async def create_role(
        req: RoleRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("admin.roles.manage"))
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


@app.get("/v1/roles")
async def list_roles(
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(require_permission("admin.roles.manage"))
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


@app.post("/v1/users/{user_id}/roles", status_code=201)
async def assign_role_to_user(
        user_id: str,
        req: AssignRoleRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "roles.assign",
                None
            )
        )
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

        # Check if assignment already exists
        existing = db.query(UserRole).filter(
            UserRole.user_id == uuid.UUID(user_id),
            UserRole.role_id == uuid.UUID(req.role_id)
        ).first()

        if existing:
            raise HTTPException(status_code=409, detail="Role already assigned to user")

        # Create assignment
        user_role = UserRole(
            id=uuid.uuid4(),
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
        raise HTTPException(status_code=409, detail="Role assignment already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="assign_role", status="error").inc()
        logger.error(f"❌ Assign role failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users/{user_id}/roles")
async def get_user_roles(
        user_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "roles.assign",
                None
            )
        )
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


@app.delete("/v1/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(
        user_id: str,
        role_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "roles.assign",
                None
            )
        )
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


@app.post("/v1/vendors", status_code=201)
async def create_vendor(
        req: VendorRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("vendors.manage"))
):
    """Create a new vendor"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_vendor", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

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

        req_total.labels(operation="create_vendor", status="success").inc()
        req_duration.labels(operation="create_vendor").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created vendor: {vendor.vendor_id} ({vendor.name})")

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


@app.get("/v1/vendors")
async def list_vendors(
        tenant_id: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(
            require_permission(
                "vendors.manage",
                None
            )
        )
):
    """List vendors with optional tenant filtering"""
    q = db.query(Vendor)
    
    if tenant_id:
        q = q.filter(Vendor.tenant_id == uuid.UUID(tenant_id))
    else:
        q = q.filter(Vendor.tenant_id == ctx.tenant_id)  # Filter by user's tenant by default

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


@app.post("/v1/cost-centres", status_code=201)
async def create_cost_centre(
        req: CostCentreRequest,
        
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("cost_centres.manage"))
):
    """Create a new cost centre"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_cost_centre", status="start").inc()

        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify manager user exists (if provided)
        manager_user_uuid = None
        if req.manager_user_id:
            manager = db.query(User).filter(User.user_id == uuid.UUID(req.manager_user_id)).first()
            if not manager:
                raise HTTPException(status_code=404, detail="Manager user not found")
            manager_user_uuid = uuid.UUID(req.manager_user_id)

        # Create cost centre
        cc = CostCentre(
            cost_centre_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            manager_user_id=manager_user_uuid,
            budget_minor=req.budget_minor,
            spent_minor=0,
            currency_code=req.currency,
            status="active"
        )
        db.add(cc)
        db.commit()
        db.refresh(cc)

        req_total.labels(operation="create_cost_centre", status="success").inc()
        req_duration.labels(operation="create_cost_centre").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created cost centre: {cc.cost_centre_id} ({cc.name})")

        return {
            "cost_centre_id": str(cc.cost_centre_id),
            "tenant_id": str(cc.tenant_id),
            "name": cc.name,
            "budget_minor": cc.budget_minor,
            "spent_minor": cc.spent_minor,
            "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
            "status": cc.status,
            "created_at": cc.created_at.isoformat()
        }
    except HTTPException:
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_cost_centre", status="error").inc()
        logger.error(f"❌ Cost centre creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/cost-centres")
async def list_cost_centres(
        tenant_id: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(
            require_permission(
                "cost_centres.manage",
                None
            )
        )
):
    """List cost centres with optional tenant filtering"""
    q = db.query(CostCentre).filter(CostCentre.status == "active")
    
    if tenant_id:
        q = q.filter(CostCentre.tenant_id == uuid.UUID(tenant_id))
    else:
        q = q.filter(CostCentre.tenant_id == ctx.tenant_id)  # Filter by user's tenant by default

    total = q.count()
    ccs = q.order_by(CostCentre.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "cost_centres": [
            {
                "cost_centre_id": str(cc.cost_centre_id),
                "tenant_id": str(cc.tenant_id),
                "name": cc.name,
                "budget_minor": cc.budget_minor,
                "spent_minor": cc.spent_minor,
                "manager_user_id": str(cc.manager_user_id) if cc.manager_user_id else None,
                "status": cc.status,
                "created_at": cc.created_at.isoformat()
            }
            for cc in ccs
        ],
        "total": total,
        "limit": limit,
        "offset": offset
    }
# ==================================================================================
# RBAC ENDPOINTS - Role-Based Access Control with Scopes
# ==================================================================================

@app.post("/v1/permissions", status_code=201)
async def create_permission(
    code: str,
    description: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.permissions.manage"))
):
    """Create a new permission"""
    try:
        # Check if exists
        existing = db.query(Permission).filter(Permission.code == code).first()
        if existing:
            raise HTTPException(status_code=409, detail="Permission already exists")
        
        perm = Permission(
            permission_id=uuid.uuid4(),
            code=code,
            description=description
        )
        db.add(perm)
        db.commit()
        db.refresh(perm)
        
        return {
            "permission_id": str(perm.permission_id),
            "code": perm.code,
            "description": perm.description
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Permission creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/v1/permissions")
async def list_permissions(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.permissions.manage"))
):
    """List all permissions"""
    permissions = db.query(Permission).all()
    return {
        "permissions": [
            {"permission_id": str(p.permission_id), "code": p.code, "description": p.description}
            for p in permissions
        ]
    }

@app.post("/v1/roles/{role_id}/permissions/{permission_id}", status_code=201)
async def add_permission_to_role(
    role_id: str,
    permission_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.roles.manage"))
):
    """Add permission to role"""
    try:
        # Check if already exists
        existing = db.query(RolePermission).filter(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id)
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="Permission already assigned to role")
        
        rp = RolePermission(
            id=uuid.uuid4(),
            role_id=uuid.UUID(role_id),
            permission_id=uuid.UUID(permission_id)
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


@app.delete("/v1/roles/{role_id}/permissions/{permission_id}", status_code=204)
async def remove_permission_from_role(
    role_id: str,
    permission_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.roles.manage"))
):
    """Remove permission from role"""
    try:
        assignment = db.query(RolePermission).filter(
            RolePermission.role_id == uuid.UUID(role_id),
            RolePermission.permission_id == uuid.UUID(permission_id)
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

@app.get("/v1/roles/{role_id}/permissions")
async def get_role_permissions(
    role_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.roles.manage"))
):
    """Get all permissions for a role"""
    role_perms = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_id == Permission.permission_id
    ).filter(
        RolePermission.role_id == uuid.UUID(role_id)
    ).all()
    
    return {
        "role_id": role_id,
        "permissions": [
            {
                "permission_id": str(p.permission_id),
                "code": p.code,
                "description": p.description
            }
            for rp, p in role_perms
        ]
    }

@app.post("/v1/roles/{role_id}/scopes", status_code=201)
async def add_scope_to_role(
    role_id: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    grant_type: str = "include",
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.scopes.manage"))
):
    """Add scope to role (tenant, site, store, cost_centre level)"""
    try:
        scope = RoleScope(
            id=uuid.uuid4(),
            role_id=uuid.UUID(role_id),
            resource_type=resource_type,
            resource_id=uuid.UUID(resource_id) if resource_id else None,
            grant_type=grant_type
        )
        db.add(scope)
        db.commit()
        
        return {
            "message": f"Scope added: {resource_type}",
            "scope_id": str(scope.id)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to add scope: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/v1/roles/{role_id}/scopes")
async def get_role_scopes(
    role_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.scopes.manage"))
):
    """Get all scopes for a role"""
    scopes = db.query(RoleScope).filter(RoleScope.role_id == uuid.UUID(role_id)).all()
    
    return {
        "role_id": role_id,
        "scopes": [
            {
                "scope_id": str(s.id),
                "resource_type": s.resource_type,
                "resource_id": str(s.resource_id) if s.resource_id else None,
                "grant_type": s.grant_type
            }
            for s in scopes
        ]
    }


@app.delete("/v1/roles/{role_id}/scopes/{scope_id}", status_code=204)
async def remove_scope_from_role(
    role_id: str,
    scope_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("admin.scopes.manage"))
):
    """Remove a scope from a role"""
    try:
        scope = db.query(RoleScope).filter(
            RoleScope.role_id == uuid.UUID(role_id),
            RoleScope.id == uuid.UUID(scope_id)
        ).first()

        if not scope:
            raise HTTPException(status_code=404, detail="Scope not found for role")

        db.delete(scope)
        db.commit()
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role or scope ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to remove scope from role: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# USER BUDGET ENDPOINTS - Cost Centre Assignments & Budget Info
# ==================================================================================

@app.post("/v1/users/{user_id}/cost-centres", status_code=201)
async def assign_user_to_cost_centre(
    user_id: str,
    cost_centre_id: str = Query(..., description="Cost centre ID"),
    allocated_budget_minor: int = Query(0, description="Initial allocated budget in minor units"),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("cost_centres.manage"))
):
    """Assign a user to a cost centre with optional budget allocation"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify cost centre exists
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == uuid.UUID(cost_centre_id)).first()
        if not cc:
            raise HTTPException(status_code=404, detail="Cost centre not found")
        
        # Check if assignment already exists
        existing = db.query(UserCostCentre).filter(
            UserCostCentre.user_id == uuid.UUID(user_id),
            UserCostCentre.cost_centre_id == uuid.UUID(cost_centre_id)
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="User already assigned to this cost centre")
        
        # Create assignment
        user_cc = UserCostCentre(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            cost_centre_id=uuid.UUID(cost_centre_id),
            allocated_budget_minor=allocated_budget_minor,
            spent_minor=0,
            currency_code=cc.currency_code
        )
        db.add(user_cc)
        db.commit()
        db.refresh(user_cc)
        
        logger.info(f"✅ Assigned user {user_id} to cost centre {cost_centre_id} with budget {allocated_budget_minor}")
        
        return {
            "id": str(user_cc.id),
            "user_id": user_id,
            "cost_centre_id": cost_centre_id,
            "allocated_budget_minor": allocated_budget_minor,
            "spent_minor": 0,
            "available_minor": allocated_budget_minor,
            "currency_code": cc.currency_code
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to assign user to cost centre: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users/{user_id}/budget")
async def get_user_budget(
    user_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage"))
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
        
        # Get cost centre info
        cc = db.query(CostCentre).filter(CostCentre.cost_centre_id == user_cc.cost_centre_id).first()
        
        available = user_cc.allocated_budget_minor - user_cc.spent_minor
        
        return {
            "user_id": user_id,
            "has_budget": True,
            "cost_centre_id": str(user_cc.cost_centre_id),
            "cost_centre_name": cc.name if cc else "Unknown",
            "allocated_budget_minor": user_cc.allocated_budget_minor,
            "spent_minor": user_cc.spent_minor,
            "available_minor": available,
            "currency_code": user_cc.currency_code,
            "cost_centre_budget_minor": cc.budget_minor if cc else 0,
            "cost_centre_spent_minor": cc.spent_minor if cc else 0,
            "cost_centre_available_minor": (cc.budget_minor - cc.spent_minor) if cc else 0
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users/{user_id}/spending-history")
async def get_user_spending_history(
    user_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage"))
):
    """Get user's spending history"""
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


# ==================================================================================
# PASSWORD MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/users/{user_id}/reset-password", status_code=200)
async def reset_user_password(
    user_id: str,
    req: PasswordResetRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.password.reset"))
):
    """Reset a user's password"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, user.tenant_id)
        
        # Hash new password
        password_hash = bcrypt.hashpw(req.new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Update password
        user.password_hash = password_hash
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        # Invalidate cached user context
        invalidate_user_context(str(user.user_id), str(user.tenant_id))
        
        logger.info(f"✅ Password reset for user: {user.user_id}")
        
        return {
            "user_id": user_id,
            "message": "Password reset successfully"
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to reset password: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ==================================================================================
# ORGANIZATIONAL UNIT ENDPOINTS
# ==================================================================================

@app.post("/v1/org-units", status_code=201)
async def create_org_unit(
    req: OrgUnitRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.manage"))
):
    """Create an organizational unit"""
    try:
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, uuid.UUID(req.tenant_id))
        
        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        # Verify parent org unit exists (if provided)
        parent_uuid = None
        if req.parent_org_unit_id:
            parent = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(req.parent_org_unit_id)).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent org unit not found")
            # Verify parent belongs to same tenant
            check_tenant_access(ctx, parent.tenant_id)
            parent_uuid = uuid.UUID(req.parent_org_unit_id)
        
        # Create org unit
        org_unit = OrgUnit(
            org_unit_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            type=req.type,
            parent_org_unit_id=parent_uuid
        )
        db.add(org_unit)
        db.commit()
        db.refresh(org_unit)
        
        logger.info(f"✅ Created org unit: {org_unit.org_unit_id} ({org_unit.name})")
        
        return {
            "org_unit_id": str(org_unit.org_unit_id),
            "tenant_id": str(org_unit.tenant_id),
            "name": org_unit.name,
            "type": org_unit.type,
            "parent_org_unit_id": str(org_unit.parent_org_unit_id) if org_unit.parent_org_unit_id else None,
            "created_at": org_unit.created_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create org unit: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/org-units")
async def list_org_units(
    tenant_id: Optional[str] = Query(None),
    parent_org_unit_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.manage"))
):
    """List organizational units"""
    try:
        q = db.query(OrgUnit)
        
        # Filter by tenant
        if tenant_id:
            check_tenant_access(ctx, uuid.UUID(tenant_id))
            q = q.filter(OrgUnit.tenant_id == uuid.UUID(tenant_id))
        else:
            q = q.filter(OrgUnit.tenant_id == ctx.tenant_id)
        
        # Filter by parent (optional)
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
                    "parent_org_unit_id": str(ou.parent_org_unit_id) if ou.parent_org_unit_id else None,
                    "created_at": ou.created_at.isoformat()
                }
                for ou in org_units
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list org units: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/org-units/{org_unit_id}/users/{user_id}", status_code=201)
async def assign_user_to_org_unit(
    org_unit_id: str,
    user_id: str,
    req: OrgUnitAssignmentRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.assign"))
):
    """Assign a user to an organizational unit"""
    try:
        # Verify org unit exists
        org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == uuid.UUID(org_unit_id)).first()
        if not org_unit:
            raise HTTPException(status_code=404, detail="Org unit not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, org_unit.tenant_id)
        
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify user belongs to same tenant
        check_tenant_access(ctx, user.tenant_id)
        
        # Verify role exists
        role = db.query(Role).filter(Role.role_id == uuid.UUID(req.role_id)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        
        # Check if assignment already exists
        existing = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == uuid.UUID(user_id),
            UserOrgAssignment.org_unit_id == uuid.UUID(org_unit_id)
        ).first()
        
        if existing:
            raise HTTPException(status_code=409, detail="User already assigned to this org unit")
        
        # Create assignment
        assignment = UserOrgAssignment(
            assignment_id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            org_unit_id=uuid.UUID(org_unit_id),
            role_id=uuid.UUID(req.role_id),
            assigned_by=uuid.UUID(ctx.user_id)
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        
        # Invalidate cached user context to refresh manager relationships
        invalidate_user_context(str(user.user_id), str(user.tenant_id))
        
        logger.info(f"✅ Assigned user {user_id} to org unit {org_unit_id}")
        
        return {
            "assignment_id": str(assignment.assignment_id),
            "user_id": user_id,
            "org_unit_id": org_unit_id,
            "role_id": req.role_id,
            "assigned_at": assignment.assigned_at.isoformat()
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to assign user to org unit: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/users/{user_id}/subordinates")
async def get_user_subordinates(
    user_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("users.manage"))
):
    """Get list of users who report to this user"""
    try:
        # Verify user exists
        user = db.query(User).filter(User.user_id == uuid.UUID(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # SECURITY: Verify tenant access
        check_tenant_access(ctx, user.tenant_id)
        
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
            User.active == True
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


@app.delete("/v1/org-units/{org_unit_id}/users/{user_id}", status_code=204)
async def remove_user_from_org_unit(
    org_unit_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("org_units.assign"))
):
    """Remove a user from an organizational unit"""
    try:
        # Find assignment
        assignment = db.query(UserOrgAssignment).filter(
            UserOrgAssignment.user_id == uuid.UUID(user_id),
            UserOrgAssignment.org_unit_id == uuid.UUID(org_unit_id)
        ).first()
        
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
        # Verify org unit exists and check tenant access
        org_unit = db.query(OrgUnit).filter(OrgUnit.org_unit_id == assignment.org_unit_id).first()
        if org_unit:
            check_tenant_access(ctx, org_unit.tenant_id)
        
        # Delete assignment
        db.delete(assignment)
        db.commit()
        
        # Invalidate cached user context
        invalidate_user_context(user_id, str(ctx.tenant_id))
        
        logger.info(f"✅ Removed user {user_id} from org unit {org_unit_id}")
        
        return Response(status_code=204)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to remove user from org unit: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")