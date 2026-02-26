"""
Tenant event worker — handles async side-effects for tenant events.

Engineering Lock v1.1 §0.5: Outbox events are immutable. Workers MUST NOT
mutate payload after insertion. This handler only performs non-critical
async tasks (notifications, external sync). Admin user creation is
synchronous in the signup endpoint.
"""

import uuid
from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent
from provisioning_service.utils.logger import logger


async def handle_tenant_created(db: Session, payload_id: str) -> None:
    """Handle async side-effects after tenant + admin user are created.

    The admin user already exists (created synchronously in the signup endpoint).
    This handler runs non-critical tasks that can safely retry:
      - Send welcome email
      - Sync to external systems
      - Future: emit to Graph/Vector projection layers
    """
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.payload or {}
    tenant_id = payload.get("tenant_id")
    admin_email = payload.get("admin_email")

    if not tenant_id:
        raise ValueError("tenant_id missing in outbox payload")

    logger.info(f"Tenant worker: processing tenant.created for {tenant_id}")

    # TODO: Send welcome email to admin_email
    # TODO: Sync tenant to external CRM / analytics
    # TODO: Graph projection — create Tenant node

    logger.info(f"Tenant worker: completed async tasks for tenant {tenant_id}")
