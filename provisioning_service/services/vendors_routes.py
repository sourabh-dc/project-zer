"""
Vendors API — vendor CRUD + vendor-user management.

Split from provisioning_routes.py (no behavior changes).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from provisioning_service.Models import Tenant, Vendor, VendorUser
from provisioning_service.Schemas import VendorRequest, VendorUpdateRequest, VendorUserCreate, VendorUserUpdate
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.core.policy_client import require_policy
from provisioning_service.core.entitlement_helpers import record_feature_usage
from provisioning_service.core.helpers.resource_loaders import vendor_quota_resource
from provisioning_service.core.helpers.outbox_helpers import create_outbox_event
from provisioning_service.utils.logger import logger
from provisioning_service.utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["Vendors"])


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
