import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, APIRouter, HTTPException, Query
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, Response

from Models import Tenant, Role, UserRole, User, Vendor, Site, Store, CostCentre, Permission, RolePermission, RoleScope
from Schemas import TenantRequest, UserContext, SiteRequest, StoreRequest, UserRequest, BulkUserRequest, \
    AssignRoleRequest, RoleRequest, CostCentreRequest, VendorRequest
from core.config import SERVICE_NAME, SERVICE_VERSION, SETTINGS
from core.db_config import SessionLocal, get_db
from core.permission_check_helpers import require_permission
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
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
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
    """Create a new site under a tenant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_site", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Create site
        site = Site(
            site_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            site_type=req.type,
            geo=req.geo
        )
        db.add(site)
        db.commit()
        db.refresh(site)

        req_total.labels(operation="create_site", status="success").inc()
        req_duration.labels(operation="create_site").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created site: {site.site_id} ({site.name})")

        return {
            "site_id": str(site.site_id),
            "tenant_id": str(site.tenant_id),
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
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant reference")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_site", status="error").inc()
        logger.error(f"❌ Site creation failed: {e}")
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
        q = db.query(Site)
        if tenant_id:
            q = q.filter(Site.tenant_id == uuid.UUID(tenant_id))

        total = q.count()
        sites = q.order_by(Site.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "sites": [
                {
                    "site_id": str(s.site_id),
                    "tenant_id": str(s.tenant_id),
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
        site_id: str = Query(..., description="Site ID"),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("stores.manage"))
):
    """Create a new store under a site"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()

        # Verify site exists and get tenant_id
        site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")

        # Create store (tenant_id auto-mapped from site)
        store = Store(
            store_id=uuid.uuid4(),
            site_id=uuid.UUID(site_id),
            tenant_id=site.tenant_id,
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

        logger.info(f"✅ Created store: {store.store_id} ({store.name})")

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
        q = db.query(Store)
        if site_id:
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
        tenant_id: str = Query(..., description="Tenant ID"),
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(require_permission("cost_centres.manage"))
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
