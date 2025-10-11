import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException
import logging

from ..repositories.vendor_repository import VendorRepository
from ..repositories.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)

class VendorService:
    def __init__(self):
        self.repo = VendorRepository()
        self.tenant_repo = TenantRepository()

    async def upsert_vendor_v2(self, vendor_id: str, payload, db: Session):
        # Convert string IDs to UUIDs if needed
        try:
            vendor_uuid = uuid.UUID(vendor_id)
        except ValueError:
            vendor_uuid = uuid.uuid4()
        try:
            tenant_uuid = uuid.UUID(payload.tenant_id)
        except ValueError:
            tenant_uuid = uuid.uuid4()

        # Validate tenant exists
        if not self.tenant_repo.get_tenant_by_id(db, tenant_uuid):
            raise HTTPException(status_code=400, detail="Tenant not found")

        vendor = self.repo.get_by_id(db, str(vendor_uuid))
        if vendor:
            vendor = self.repo.update_vendor(db, vendor, payload.name, payload.description, payload.rating)
            logger.info("vendor_updated", extra={"vendor_id": str(vendor_uuid)})
            return {"vendor_id": str(vendor.vendor_id), "tenant_id": str(vendor.tenant_id), "name": vendor.name, "updated": True}
        v = self.repo.create_vendor(db, str(vendor_uuid), str(tenant_uuid), payload.name, payload.description, payload.rating)
        logger.info("vendor_created", extra={"vendor_id": str(vendor_uuid)})
        return {"vendor_id": str(v.vendor_id), "tenant_id": str(v.tenant_id), "name": v.name, "created": True}

