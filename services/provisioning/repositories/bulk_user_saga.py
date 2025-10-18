import time
import uuid
from datetime import datetime
from typing import List, Dict

from sqlalchemy import text
from prometheus_client import Counter, Histogram

from .db_handler import audit
from ..services.subscription_service import get_limits
from ..utils.provisioning_logger import logger
from ..models import UserV2, TenantV2
from outbox_repository import store_outbox
from ..tasks.celery_tasks import publish_outbox_events
from ..utils.user_auth import gen_api_key

req_total = Counter('prov_requests_total', 'Requests', ['op', 'status'])
req_duration = Histogram('prov_duration_seconds', 'Duration', ['op'])
saga_total = Counter('prov_saga_total', 'Sagas', ['type', 'status'])
saga_duration = Histogram('prov_saga_duration_seconds', 'Saga duration', ['type'])


class BulkUserSaga:
    """Saga for bulk user import - Pro/Enterprise feature"""

    def __init__(self, db):
        self.db = db
        self.created_users = []
        self.created_events = []

    async def exec(self, tenant_id: str, users_data: List[Dict], uctx: Dict, auto_generate_api_keys: bool = False):
        start = time.time()
        sid = f"saga_bulk_users_{uuid.uuid4().hex[:8]}"
        results = {"success": [], "failed": []}

        try:
            # Validate tenant exists
            t = self.db.query(TenantV2).filter(TenantV2.tenant_id == uuid.UUID(tenant_id)).first()
            if not t:
                raise ValueError(f"Tenant {tenant_id} not found")

            # Check entitlement for bulk user import (Pro/Ent feature)
            limits = await get_limits(tenant_id)
            max_users = limits.get("max_users", 100)
            current_user_count = self.db.query(UserV2).filter(
                UserV2.tenant_id == uuid.UUID(tenant_id),
                UserV2.active == True
            ).count()

            if current_user_count + len(users_data) > max_users:
                raise ValueError(
                    f"Bulk import would exceed user limit ({max_users}). Current: {current_user_count}, Requested: {len(users_data)}")

            # Create users
            for user_data in users_data:
                try:
                    email = user_data.get("email")
                    display_name = user_data.get("display_name", email)
                    permissions = user_data.get("permissions", [])

                    if not email:
                        results["failed"].append({"error": "Missing email", "data": user_data})
                        continue

                    # Check if user already exists
                    if self.db.query(UserV2).filter(UserV2.email == email).first():
                        results["failed"].append({"email": email, "error": "Email already exists"})
                        continue

                    # Create user
                    user_id = uuid.uuid4()
                    api_key = gen_api_key() if auto_generate_api_keys else None
                    new_user = UserV2(
                        user_id=user_id,
                        tenant_id=tenant_id,
                        email=email,
                        display_name=display_name,
                        active=True,
                        api_key=api_key,
                        api_key_created_at=datetime.now() if api_key else None,
                        permissions=permissions
                    )
                    self.db.add(new_user)
                    self.db.flush()
                    self.created_users.append(new_user)

                    # Create outbox event
                    event_id = store_outbox(self.db, "USER_CREATED", tenant_id, str(user_id), {
                        "user_id": str(user_id),
                        "email": email,
                        "display_name": display_name,
                        "bulk_import": True
                    })
                    self.created_events.append(event_id)

                    # Audit log
                    audit(self.db, tenant_id, uctx["user_id"], "CREATE", "user", str(user_id), {
                        "email": email,
                        "bulk_import": True
                    })

                    results["success"].append({
                        "user_id": str(user_id),
                        "email": email,
                        "api_key": api_key
                    })

                except Exception as user_error:
                    results["failed"].append({
                        "email": user_data.get("email", "unknown"),
                        "error": str(user_error)
                    })

            # Commit all changes
            self.db.commit()

            # Trigger outbox publishing
            publish_outbox_events.delay()

            saga_total.labels(type="bulk_users", status="ok").inc()
            saga_duration.labels(type="bulk_users").observe(time.time() - start)

            return {
                "saga_id": sid,
                "tenant_id": tenant_id,
                "total_requested": len(users_data),
                "success_count": len(results["success"]),
                "failed_count": len(results["failed"]),
                "results": results
            }

        except Exception as e:
            await self.comp()
            saga_total.labels(type="bulk_users", status="fail").inc()
            raise

    async def comp(self):
        """Compensation: rollback created users and events"""
        try:
            for event_id in self.created_events:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": event_id})

            for user in self.created_users:
                self.db.delete(user)

            self.db.commit()
        except Exception as e:
            logger.error(f"BulkUserSaga compensation failed: {e}")
            self.db.rollback()