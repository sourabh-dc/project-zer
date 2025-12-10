import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from Models import Store, SiteTenant
from Schemas import StoreRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger
from utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["stores"])


@router.post("/stores", status_code=201)
async def create_store(req: StoreRequest, db: Session = Depends(get_db)):
    start = datetime.now()
    try:
        req_total.labels(operation="create_store", status="start").inc()

        site_tenant = (
            db.query(SiteTenant)
            .filter(SiteTenant.site_id == uuid.UUID(req.site_id), SiteTenant.tenant_id == req.tenant_id)
            .first()
        )
        if not site_tenant:
            raise HTTPException(status_code=404, detail="Site not found or not accessible by your tenant")

        store = Store(
            store_id=uuid.uuid4(),
            site_id=uuid.UUID(req.site_id),
            tenant_id=req.tenant_id,
            name=req.name,
            store_type=req.type,
            geo=req.geo,
        )
        db.add(store)
        db.commit()
        db.refresh(store)

        req_total.labels(operation="create_store", status="success").inc()
        req_duration.labels(operation="create_store").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Created store: {store.store_id} ({store.name}) for tenant: {req.tenant_id}")
        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id),
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "created_at": store.created_at.isoformat(),
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


@router.put("/stores/{store_id}")
async def update_store(
    store_id: str,
    name: Optional[str] = Query(None, description="New store name"),
    store_type: Optional[str] = Query(None, description="New store type"),
    geo: Optional[str] = Query(None, description="New geo location"),
    db: Session = Depends(get_db),
):
    start = datetime.now()
    try:
        req_total.labels(operation="update_store", status="start").inc()

        store = db.query(Store).filter(Store.store_id == uuid.UUID(store_id)).first()
        if not store:
            raise HTTPException(status_code=404, detail="Store not found")

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
        req_duration.labels(operation="update_store").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Updated store: {store.store_id} ({store.name})")
        return {
            "store_id": str(store.store_id),
            "site_id": str(store.site_id),
            "tenant_id": str(store.tenant_id),
            "name": store.name,
            "store_type": store.store_type,
            "geo": store.geo,
            "updated_at": store.updated_at.isoformat(),
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
    ctx: UserContext = Depends(require_permission("stores.manage")),
):
    q = db.query(Store).filter(Store.tenant_id == ctx.tenant_id)

    if site_id:
        site_access = (
            db.query(SiteTenant)
            .filter(SiteTenant.site_id == uuid.UUID(site_id), SiteTenant.tenant_id == ctx.tenant_id)
            .first()
        )
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
                "created_at": s.created_at.isoformat(),
            }
            for s in stores
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

