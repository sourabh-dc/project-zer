"""
Tenants API — tenant CRUD.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, User, Site, Store, SiteTenant
from provisioning_service.Schemas import TenantUpdateRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total
from provisioning_service.utils.redis_client import redis_client

router = APIRouter(prefix="/provisioning", tags=["Tenants"])


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
