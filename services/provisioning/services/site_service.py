import uuid
from sqlalchemy.orm import Session
from pydantic import ValidationError
from fastapi import HTTPException

from services.provisioning.core.recording_service import record_provisioning_metric
from ..repositories.site_repository import SiteRepository
# Import your models and utilities here
from services.provisioning.core.subscription_limits import SubscriptionLimits
import logging

from ..repositories.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)

class SiteService:
    def __init__(self):
        self.repo = SiteRepository()
        self.tenant_repo = TenantRepository()

    async def upsert_site_v2(self, site_id: str, payload, tenant_id: str, db: Session):
        # Convert string IDs to UUIDs if needed
        try:
            site_uuid = uuid.UUID(site_id)
        except ValueError:
            site_uuid = uuid.uuid4()
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            tenant_uuid = uuid.uuid4()

        # Enforce subscription limits
        try:
            await SubscriptionLimits.enforce_limits(tenant_id, "create_site", db)
        except ValidationError as e:
            record_provisioning_metric("create_site", "limit_exceeded", tenant_id)
            raise HTTPException(status_code=400, detail=str(e))

        # Validate tenant exists
        if not self.tenant_repo.get_tenant_by_id(db, tenant_uuid):
            record_provisioning_metric("create_site", "tenant_not_found", tenant_id)
            raise HTTPException(status_code=400, detail="Tenant not found")

        s = self.repo.get_site_by_id(db, site_uuid)
        if s:
            s = self.repo.update_site(db, s, payload.name, payload.site_type, payload.geo)
            logger.info("site_updated", extra={"site_id": str(site_uuid)})
            record_provisioning_metric("update_site", "success", tenant_id)
            return {"site_id": str(s.site_id), "name": s.name, "site_type": s.site_type, "geo": s.geo, "updated": True}
        s = self.repo.create_site(db, str(tenant_uuid), payload.name, payload.site_type, payload.geo)
        logger.info("site_created", extra={"site_id": str(site_uuid)})
        record_provisioning_metric("create_site", "success", tenant_id)
        return {"site_id": str(s.site_id), "name": s.name, "site_type": s.site_type, "geo": s.geo, "created": True}

