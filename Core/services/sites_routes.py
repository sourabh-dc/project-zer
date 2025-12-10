import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Models import Tenant, Site, SiteTenant
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
                "name": t.tenant_name,
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
        "name": tenant.tenant_name,
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
            .filter(Tenant.tenant_name == name, Tenant.tenant_id != uuid.UUID(tenant_id))
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
        "name": tenant.tenant_name,
        "type": tenant.tenant_type,
        "active": tenant.active,
        "updated_at": tenant.updated_at.isoformat() if tenant.updated_at else None,
    }


@router.post("/sites", status_code=201)
async def create_site(req: SiteRequest, db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    site = Site(
        site_id=uuid.uuid4(),
        name=req.name,
        site_type=req.type,
        geo=req.geo,
    )
    db.add(site)
    db.flush()

    site_tenant = SiteTenant(
        id=uuid.uuid4(),
        site_id=site.site_id,
        tenant_id=uuid.UUID(req.tenant_id),
    )
    db.add(site_tenant)
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
    site = db.query(Site).filter(Site.site_id == uuid.UUID(site_id)).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    existing = (
        db.query(SiteTenant)
        .filter(SiteTenant.site_id == uuid.UUID(site_id), SiteTenant.tenant_id == uuid.UUID(tenant_id))
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Site is already associated with this tenant")

    site_tenant = SiteTenant(
        id=uuid.uuid4(),
        site_id=uuid.UUID(site_id),
        tenant_id=uuid.UUID(tenant_id),
    )
    db.add(site_tenant)
    db.commit()

    logger.info(f"✅ Added tenant {tenant_id} to site {site_id}")
    return {
        "site_id": site_id,
        "tenant_id": tenant_id,
        "associated": True,
    }


@router.get("/sites/{site_id}/tenants")
async def list_site_tenants(
    site_id: str,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage")),
):
    site_access = (
        db.query(SiteTenant)
        .filter(SiteTenant.site_id == uuid.UUID(site_id), SiteTenant.tenant_id == ctx.tenant_id)
        .first()
    )
    if not site_access:
        raise HTTPException(status_code=404, detail="Site not found or not accessible by your tenant")

    tenants = (
        db.query(Tenant)
        .join(SiteTenant, Tenant.tenant_id == SiteTenant.tenant_id)
        .filter(SiteTenant.site_id == uuid.UUID(site_id))
        .all()
    )

    return {
        "site_id": site_id,
        "tenants": [
            {
                "tenant_id": str(t.tenant_id),
                "name": t.tenant_name,
                "type": t.tenant_type,
                "created_at": t.created_at.isoformat(),
            }
            for t in tenants
        ],
        "total": len(tenants),
    }


@router.delete("/sites/{site_id}/tenants/{tenant_id}", status_code=204)
async def remove_tenant_from_site(site_id: str, tenant_id: str, db: Session = Depends(get_db)):
    site_tenant = (
        db.query(SiteTenant)
        .filter(SiteTenant.site_id == uuid.UUID(site_id), SiteTenant.tenant_id == uuid.UUID(tenant_id))
        .first()
    )
    if not site_tenant:
        raise HTTPException(status_code=404, detail="Site-tenant association not found")

    tenant_count = db.query(SiteTenant).filter(SiteTenant.site_id == uuid.UUID(site_id)).count()
    if tenant_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the only tenant from a site")

    db.delete(site_tenant)
    db.commit()

    logger.info(f"✅ Removed tenant {tenant_id} from site {site_id}")
    return {}


@router.get("/sites")
async def list_sites(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("sites.manage")),
):
    q = db.query(Site).join(SiteTenant, Site.site_id == SiteTenant.site_id)
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
                "created_at": s.created_at.isoformat(),
            }
            for s in sites
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

