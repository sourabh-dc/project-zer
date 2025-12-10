import uuid
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from Models import Vendor
from Schemas import VendorRequest, UserContext
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger
from utils.metrics import req_total, req_duration

router = APIRouter(prefix="/provisioning", tags=["vendors"])


@router.post("/vendors", status_code=201)
async def create_vendor(req: VendorRequest, db: Session = Depends(get_db)):
    start = datetime.now()
    try:
        req_total.labels(operation="create_vendor", status="start").inc()

        if not db.query(Vendor).filter(Vendor.tenant_id == uuid.UUID(req.tenant_id)).first():
            # tenant existence implied by FK; skip explicit check
            pass

        vendor = Vendor(
            vendor_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            contact_email=req.contact_email,
            description=req.description,
            status="active",
        )
        db.add(vendor)
        db.commit()
        db.refresh(vendor)

        req_total.labels(operation="create_vendor", status="success").inc()
        req_duration.labels(operation="create_vendor").observe((datetime.now() - start).total_seconds())

        logger.info(f"✅ Created vendor: {vendor.vendor_id} ({vendor.name})")
        return {
            "vendor_id": str(vendor.vendor_id),
            "tenant_id": str(vendor.tenant_id),
            "name": vendor.name,
            "contact_email": vendor.contact_email,
            "status": vendor.status,
            "created_at": vendor.created_at.isoformat(),
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


@router.get("/vendors")
async def list_vendors(
    tenant_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    limit: int = Query(100, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    ctx: UserContext = Depends(require_permission("vendors.manage", None)),
):
    q = db.query(Vendor)
    if tenant_id:
        q = q.filter(Vendor.tenant_id == uuid.UUID(tenant_id))
    else:
        q = q.filter(Vendor.tenant_id == ctx.tenant_id)

    total = q.count()
    vendors = q.order_by(Vendor.created_at.desc()).limit(limit).offset(offset).all()

    return {
        "vendors": [
            {
                "vendor_id": str(v.vendor_id),
                "tenant_id": str(v.tenant_id),
                "name": v.name,
                "status": v.status,
                "created_at": v.created_at.isoformat(),
            }
            for v in vendors
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

