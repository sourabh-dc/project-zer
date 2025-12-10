import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Models import Tenant, Site
from Schemas import UserContext, SiteRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger

router = APIRouter(prefix="/provisioning", tags=["sites"])


@router.get("/tenants")
async def list_tenants(
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
):
    total = db.query(Tenant).filter(Tenant.active == True).count()  # noqa: E712
    tenants = (
        db.query(Tenant)
        .filter(Tenant.active == True)  # noqa: E712
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
                "created_at": t.created_at.isoformat(),
            }
            for t in tenants
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant_id": str(tenant.tenant_id),
        "name": tenant.name,
        "type": tenant.tenant_type,
        "active": tenant.active,
        "created_at": tenant.created_at.isoformat(),
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
    }


@router.put("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    name: Optional[str] = Query(None, description="New tenant name"),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if name:
        existing = (
            db.query(Tenant)
            .filter(Tenant.name == name, Tenant.tenant_id != uuid.UUID(tenant_id))
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Tenant name already exists")
        tenant.name = name

    tenant.updated_at = tenant.updated_at or tenant.created_at
    db.commit()
    db.refresh(tenant)

    logger.info(f"✅ Updated tenant: {tenant.tenant_id}")
    return {
        "tenant_id": str(tenant.tenant_id),
        "name": tenant.name,
        "type": tenant.tenant_type,
        "active": tenant.active,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
    }


@router.post("/sites", status_code=201)
async def create_site(
    req: SiteRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage"))
):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    site = Site(
        site_id=uuid.uuid4(),
        tenant_id=tenant.tenant_id,
        name=req.name,
        site_type=req.site_type,
        geo=req.geo,
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    logger.info(f"✅ Created site: {site.site_id} ({site.name}) for tenant: {req.tenant_id}")
    return {
        "site_id": str(site.site_id),
        "name": site.name,
        "site_type": site.site_type,
        "created_at": site.created_at.isoformat(),
    }


@router.post("/sites/{site_id}/tenants/{tenant_id}", status_code=201)
async def add_tenant_to_site(site_id: str, tenant_id: str, db: Session = Depends(get_db)):
    raise HTTPException(status_code=400, detail="Sites now belong to a single tenant; association API removed")


@router.get("/sites/{site_id}/tenants")
async def list_site_tenants(
    site_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage")),
):
    site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
    if not site or site.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Site not found or not accessible by your tenant")

    tenant = db.query(Tenant).filter(Tenant.tenant_id == site.tenant_id).first()
    return {
        "site_id": site_id,
        "tenants": [
            {
                "tenant_id": str(tenant.tenant_id),
                "name": tenant.name,
                "type": tenant.tenant_type,
                "created_at": tenant.created_at.isoformat(),
            }
        ],
        "total": 1,
    }


@router.delete("/sites/{site_id}/tenants/{tenant_id}", status_code=400)
async def remove_tenant_from_site(site_id: str, tenant_id: str, db: Session = Depends(get_db)):
    raise HTTPException(status_code=400, detail="Sites are single-tenant; removal not supported")


@router.get("/sites")
async def list_sites(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage")),
):
    q = db.query(Site)
    if tenant_id:
        q = q.filter(Site.tenant_id == uuid.UUID(tenant_id))
    else:
        q = q.filter(Site.tenant_id == ctx.tenant_id)

    total = q.count()
    sites = q.order_by(Site.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "sites": [
            {
                "site_id": str(s.site_id),
                "name": s.name,
                "site_type": s.site_type,
                "created_at": s.created_at.isoformat(),
            }
            for s in sites
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

