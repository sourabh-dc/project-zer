import uuid
from datetime import datetime
import logging

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.provisioning.core.recording_service import record_provisioning_metric
from ..utils.helpers import set_rls_context
from ..repositories.tenant_repository import TenantRepository
from ..core.provisioning_saga import ProvisioningSaga

from zeroque_common.communication import (
    ServiceEvent, ServiceEventType,
    event_store
)

logger = logging.getLogger(__name__)

class TenantService:
    def __init__(self):
        self.tenant_repository = TenantRepository()
        self.provisioning_saga = ProvisioningSaga()
        self.event_store = event_store

    async def create_tenant_v2(self, payload, service_name):
        correlation_id = f"tenant_{datetime.now().isoformat()}"
        tenant_id = str(uuid.uuid4())
        tenant_data = {
            "tenant_id": tenant_id,
            "name": payload.name,
            "type": payload.type,
            "scenario_id": payload.scenario_id,
            "correlation_id": correlation_id
        }
        result = await self.provisioning_saga.execute_tenant_provisioning_saga(tenant_data)
        await self.event_store.append_event(ServiceEvent(
            event_type=ServiceEventType.SERVICE_STARTED,
            service_name=service_name,
            correlation_id=correlation_id,
            data=result,
            metadata={"enhanced": True, "saga_completed": True},
            timestamp=datetime.now()
        ))
        return {
            "tenant_id": result["tenant_id"],
            "name": payload.name,
            "type": payload.type,
            "status": "created",
            "created_at": datetime.now(),
            "saga_id": correlation_id
        }

    async def upsert_tenant_v2(self, tenant_id: str, payload, db):
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            tenant_uuid = uuid.uuid4()

        # Set RLS context
        set_rls_context(db, tenant_id=str(tenant_uuid))

        # Check if tenant exists
        existing = self.tenant_repository.get_by_id(db, str(tenant_uuid))

        if existing:
            # Update existing tenant
            self.tenant_repository.update(db, str(tenant_uuid),
                                          name=payload.name,
                                          type=payload.type)
            logger.info("tenant_updated", extra={"tenant_id": str(tenant_uuid)})
            record_provisioning_metric("update_tenant", "success", str(tenant_uuid))
            return {"tenant_id": str(tenant_uuid), "name": payload.name, "type": payload.type, "updated": True}
        else:
            # Create new tenant
            self.tenant_repository.create_tenant(db, tenant_id, payload.name, payload.type, payload.scenario_id)
            logger.info("tenant_created", extra={"tenant_id": str(tenant_uuid)})
            record_provisioning_metric("create_tenant", "success", str(tenant_uuid))
            return {"tenant_id": str(tenant_uuid), "name": payload.name, "type": payload.type, "created": True}

    async def upsert_tenant_link_v2(self, payload, db: Session):
        """Create a parent→child tenant link (V2 architecture)."""
        try:
            # Validate parent and child tenants exist
            if not self.tenant_repository.get_by_id(db, payload.parent_tenant_id):
                raise HTTPException(status_code=400, detail="Parent tenant not found")
            if not self.tenant_repository.get_by_id(db, payload.child_tenant_id):
                raise HTTPException(status_code=400, detail="Child tenant not found")

            # Check if link already exists
            existing = self.tenant_repository.check_relationship(db, payload.parent_tenant_id, payload.child_tenant_id, payload.relationship)
            if existing:
                logger.info("tenant_link_exists", extra={"id": existing[0]})
                return {"id": existing[0], "exists": True}

            # Create new link
            link_id = self.tenant_repository.create_relationship(db, payload.parent_tenant_id, payload.child_tenant_id, payload.relationship)
            logger.info("tenant_link_created", extra={"id": link_id})
            return {"id": link_id, "created": True}
        except Exception as e:
            logger.error(f"Error creating tenant link: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")