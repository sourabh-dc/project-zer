import json
import uuid
import asyncio
import logging
import bcrypt
import sys
from pathlib import Path

# Add project root to path for direct script execution
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Use the ASYNC versions for Service Bus
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient

# Your internal imports
from provisioning_service.Models import User, Role, Permission, RolePermission, UserRole
from provisioning_service.core.db_config import SessionLocal

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

SB_NAMESPACE = "zeroque.servicebus.windows.net"
QUEUE_NAME = "tenant-signup-queue"


async def process_signup():
    cred = DefaultAzureCredential()
    # Use the async client
    client = ServiceBusClient(SB_NAMESPACE, cred)

    async with client:
        receiver = client.get_queue_receiver(QUEUE_NAME)
        async with receiver:
            logger.info("Worker started. Listening for messages...")
            async for msg in receiver:
                # 1. Load data from message
                data = json.loads(str(msg))
                db = SessionLocal()

                try:
                    tenant_id = data.get("tenant_id")
                    logger.info(f"Processing signup for tenant: {tenant_id}")

                    # 2. Re-create the logic using 'data' dictionary instead of 'req'
                    password_raw = data.get("password")
                    password_hash = bcrypt.hashpw(
                        password_raw.encode("utf-8"),
                        bcrypt.gensalt(12)
                    ).decode("utf-8")

                    # create user
                    user = User(
                        user_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        first_name=data.get("admin_firstname"),
                        last_name=data.get("admin_lastname"),
                        display_name=f"{data.get('admin_firstname')} {data.get('admin_lastname')}",
                        email=data.get("admin_email"),
                        password_hash=password_hash
                    )
                    db.add(user)

                    # ensure tenant_admin role exists
                    role = db.query(Role).filter(Role.code == "tenant_admin").first()
                    if not role:
                        role = Role(role_id=uuid.uuid4(), code="tenant_admin", description="Super admin for tenant")
                        db.add(role)
                        db.flush()

                    # ensure core permissions exist
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

                    # 3. Mark message as finished in Service Bus
                    await receiver.complete_message(msg)
                    logger.info(f"Successfully set up tenant {tenant_id}")

                except Exception as e:
                    db.rollback()
                    logger.error(f"Error processing message: {str(e)}")
                    # Message will return to queue for retry automatically
                    # because we didn't call complete_message()
                finally:
                    db.close()


if __name__ == "__main__":
    try:
        asyncio.run(process_signup())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")