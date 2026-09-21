"""
Stores API — store CRUD.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Store, SiteTenant
from provisioning_service.Schemas import UserContext, StoreRequest, StoreUpdateRequest
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.entitlement_helpers import record_feature_usage
from provisioning_service.core.helpers.resource_loaders import store_quota_resource
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["Stores"])


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
