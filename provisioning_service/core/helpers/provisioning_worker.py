import json
import uuid
import asyncio
import logging
import bcrypt
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path for direct script execution
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Use the ASYNC versions for Service Bus
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient

# Your internal imports
from provisioning_service.Models import (
    User, Role, Permission, RolePermission, UserRole, OutboxEvent
)
from provisioning_service.core.db_config import SessionLocal

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

SB_NAMESPACE = "zeroque.servicebus.windows.net"
QUEUE_NAME = "tenant-signup-queue"


def _decode_message_body(msg):
    """Safely decode the service bus message body to a Python object.
    Handles cases where `msg.body` yields an iterable of bytes/strings.
    """
    try:
        # msg.body may be an iterable of bytes/parts
        body_bytes = b""
        if hasattr(msg, "body"):
            for part in msg.body:
                if isinstance(part, (bytes, bytearray)):
                    body_bytes += bytes(part)
                else:
                    body_bytes += str(part).encode("utf-8")
        else:
            # fallback to str(msg)
            body_bytes = str(msg).encode("utf-8")

        text = body_bytes.decode("utf-8")
        return json.loads(text)
    except Exception as exc:
        logger.error(f"Failed to decode message body: {exc}")
        return None


async def process_signup():
    cred = DefaultAzureCredential()
    # Use the async client
    client = ServiceBusClient(SB_NAMESPACE, cred)

    async with client:
        receiver = client.get_queue_receiver(QUEUE_NAME)
        async with receiver:
            logger.info("Worker started. Listening for messages...")
            async for msg in receiver:
                db = SessionLocal()

                try:
                    data = _decode_message_body(msg)
                    if not data:
                        logger.error("Empty/invalid message body; completing message")
                        await receiver.complete_message(msg)
                        continue

                    outbox_id = data.get("outbox_id") or data.get("id")
                    if not outbox_id:
                        logger.error("No outbox_id found in message; completing message")
                        await receiver.complete_message(msg)
                        continue

                    try:
                        outbox_uuid = uuid.UUID(outbox_id)
                    except Exception:
                        logger.error("Invalid outbox_id format; completing message")
                        await receiver.complete_message(msg)
                        continue

                    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == outbox_uuid).first()
                    if not outbox:
                        logger.error(f"Outbox event not found for id {outbox_id}; completing message")
                        await receiver.complete_message(msg)
                        continue

                    # Skip if already processed
                    if outbox.status in ("completed", "failed"):
                        logger.info(f"Outbox {outbox_id} already processed with status={outbox.status}; completing message")
                        await receiver.complete_message(msg)
                        continue

                    # mark processing
                    outbox.status = "processing"
                    outbox.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    # event payload
                    payload = outbox.event_data or {}

                    tenant_id = payload.get("tenant_id")
                    logger.info(f"Processing signup for tenant: {tenant_id} (outbox={outbox_id})")

                    # 2. Re-create the logic using 'payload' dictionary
                    password_raw = payload.get("password")
                    if not password_raw:
                        # no password provided -> generate random temporary password
                        password_raw = uuid.uuid4().hex[:12]

                    password_hash = bcrypt.hashpw(
                        password_raw.encode("utf-8"),
                        bcrypt.gensalt(12)
                    ).decode("utf-8")

                    # create user (admin)
                    user = User(
                        user_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        first_name=payload.get("admin_firstname") or payload.get("first_name") or "Admin",
                        last_name=payload.get("admin_lastname") or payload.get("last_name") or "",
                        display_name=f"{payload.get('admin_firstname', '')} {payload.get('admin_lastname', '')}".strip(),
                        email=payload.get("admin_email") or payload.get("email"),
                        password_hash=password_hash
                    )
                    db.add(user)

                    # ensure tenant_admin role exists
                    role = db.query(Role).filter(Role.code == "tenant_admin").first()
                    if not role:
                        role = Role(role_id=uuid.uuid4(), code="tenant_admin", description="Super admin for tenant")
                        db.add(role)
                        db.flush()

                    # ensure core permissions exist and role-permission mappings
                    core_permissions = [
                        ("tenant.admin", "Full tenant administration"),
                        ("users.manage", "Create and manage users"),
                        ("sites.manage", "Create and manage sites"),
                        ("stores.manage", "Create and manage stores"),
                        ("vendors.manage", "Create and manage vendors"),
                        ("budgets.manage", "Manage budgets and cost centres"),
                        ("approvals.manage", "Manage approval chains and requests"),
                        ("catalog.manage", "Manage products and catalog"),
                    ]

                    for perm_code, perm_desc in core_permissions:
                        perm = db.query(Permission).filter(Permission.code == perm_code).first()
                        if not perm:
                            perm = Permission(permission_id=uuid.uuid4(), code=perm_code, description=perm_desc)
                            db.add(perm)
                            db.flush()

                        existing_rp = db.query(RolePermission).filter(
                            RolePermission.role_code == role.code,
                            RolePermission.permission_code == perm_code
                        ).first()
                        if not existing_rp:
                            db.add(RolePermission(id=uuid.uuid4(), role_code=role.code, permission_code=perm_code))

                    # assign role to user
                    user_role = UserRole(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        user_id=user.user_id,
                        role_id=role.role_id
                    )
                    db.add(user_role)

                    # Final Commit
                    db.commit()

                    # update outbox status
                    outbox.status = "completed"
                    outbox.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    # Mark message as finished in Service Bus
                    await receiver.complete_message(msg)
                    logger.info(f"Successfully set up tenant {tenant_id} (outbox={outbox_id})")

                except Exception as e:
                    # Attempt retry logic
                    try:
                        db.rollback()
                        # reload outbox in case of state change
                        if 'outbox' in locals() and outbox:
                            outbox.retry_count = (outbox.retry_count or 0) + 1
                            outbox.updated_at = datetime.now(timezone.utc)
                            if outbox.retry_count >= (outbox.max_retries or 3):
                                outbox.status = "failed"
                                db.commit()
                                logger.error(f"Outbox {outbox_id} failed after max retries: {e}")
                                await receiver.complete_message(msg)
                            else:
                                db.commit()
                                logger.error(f"Transient error processing outbox {outbox_id}, abandoning message for retry: {e}")
                                await receiver.abandon_message(msg)
                        else:
                            logger.error(f"Error processing message (no outbox): {e}")
                            await receiver.complete_message(msg)
                    except Exception as inner_exc:
                        logger.error(f"Error during error handling: {inner_exc}")
                        # complete the message to avoid poison messages
                        try:
                            await receiver.complete_message(msg)
                        except Exception:
                            pass
                finally:
                    db.close()


if __name__ == "__main__":
    try:
        asyncio.run(process_signup())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")