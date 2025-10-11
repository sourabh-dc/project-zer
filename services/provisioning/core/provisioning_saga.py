import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import HTTPException
from zeroque_common.communication import ( ServiceEventType,
    SagaOrchestrator, SagaStep,
    # Global instances
    service_bus
)
from zeroque_common.db.session import SessionLocal

from services.provisioning.models import TenantV2

logger = logging.getLogger(__name__)

# Saga implementation for provisioning operations
class ProvisioningSaga:
    """Saga for managing provisioning operations across multiple services"""

    def __init__(self):
        self.saga_orchestrator = SagaOrchestrator()
        self.steps = [
            SagaStep("validate_tenant", self.validate_tenant, self.compensate_tenant),
            SagaStep("create_tenant", self.create_tenant_record, self.delete_tenant_record),
            SagaStep("setup_permissions", self.setup_permissions, self.remove_permissions),
            SagaStep("notify_services", self.notify_services, None)
        ]

    async def execute_tenant_provisioning_saga(self, tenant_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the complete tenant provisioning saga"""
        saga_id = f"tenant_provision_{int(datetime.now().timestamp())}"

        try:
            result = await self.saga_orchestrator.execute_saga(
                saga_id=saga_id,
                steps=self.steps,
                initial_data=tenant_data
            )

            # Publish tenant provisioned event
            await service_bus.publish_to_service(
                target_service="billing",
                event_type=ServiceEventType.SERVICE_STARTED,
                data={
                    "tenant_id": result["tenant_id"],
                    "type": result["type"],
                    "saga_id": saga_id
                },
                correlation_id=saga_id
            )

            return result

        except Exception as e:
            logger.error(f"Tenant provisioning saga {saga_id} failed: {str(e)}")
            raise

    async def validate_tenant(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate tenant data"""
        logger.info(f"Validating tenant: {data}")

        # Validate tenant name uniqueness
        db = SessionLocal()
        try:
            existing = db.query(TenantV2).filter(TenantV2.name == data["name"]).first()
            if existing:
                raise HTTPException(status_code=400, detail="Tenant name already exists")

            return {"tenant_validated": True}

        finally:
            db.close()

    async def create_tenant_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create tenant record"""
        logger.info(f"Creating tenant record: {data}")

        db = SessionLocal()
        try:
            tenant = TenantV2(
                tenant_id=data["tenant_id"],
                name=data["name"],
                type=data.get("type", "customer"),
                scenario_id=data.get("scenario_id")
            )
            db.add(tenant)
            db.commit()

            return {"tenant_id": str(tenant.tenant_id), "tenant_created": True}

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create tenant record: {str(e)}")
            raise
        finally:
            db.close()

    async def setup_permissions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Setup default permissions for tenant"""
        logger.info(f"Setting up permissions for tenant: {data}")

        # Publish permission setup event
        await service_bus.publish_to_service(
            target_service="rbac",
            event_type=ServiceEventType.SERVICE_STARTED,
            data={
                "tenant_id": data["tenant_id"],
                "type": data["type"]
            },
            correlation_id=data.get("saga_id", "")
        )

        return {"permissions_setup": True}

    async def notify_services(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Notify other services about tenant creation"""
        logger.info(f"Notifying services about tenant: {data}")

        # Notify inventory service
        await service_bus.publish_to_service(
            target_service="inventory",
            event_type=ServiceEventType.SERVICE_STARTED,
            data={
                "tenant_id": data["tenant_id"],
                "type": data["type"]
            },
            correlation_id=data.get("saga_id", "")
        )

        return {"services_notified": True}

    # Compensation methods
    async def compensate_tenant(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compensate tenant validation"""
        logger.info(f"Compensating tenant validation: {data}")
        return {}

    async def delete_tenant_record(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Delete tenant record"""
        logger.info(f"Deleting tenant record: {data}")

        db = SessionLocal()
        try:
            db.query(TenantV2).filter(TenantV2.tenant_id == data["tenant_id"]).delete()
            db.commit()
            return {"tenant_deleted": True}
        finally:
            db.close()

    async def remove_permissions(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove permissions"""
        logger.info(f"Removing permissions: {data}")
        return {"permissions_removed": True}