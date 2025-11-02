from datetime import datetime, timezone, timedelta
from typing import Dict, Any
import json
from sqlalchemy import text

from ..core.celery_config import celery_app
from ..repositories.db_config import SessionLocal, set_rls_context
from ..models import EntryCode
from ..utils.entry_logger import logger
from ..utils.metrics import entry_operations_total
from ..core.redis_config import redis_client
# =============================================================================
# CELERY TASKS
# =============================================================================
def generate_entry_code() -> str:
    """Generate a unique entry code"""
    import random
    import string

    # Generate a 8-character alphanumeric code
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(8))

@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_codes(self):
    """Clean up expired entry codes"""
    try:
        with SessionLocal() as db:
            # Clean up expired codes from database
            expired_codes = db.query(EntryCode).filter(
                EntryCode.expires_at < datetime.now(timezone.utc),
                EntryCode.status == "active"
            ).all()

            for code in expired_codes:
                code.status = "expired"

                # Remove from Redis
                redis_key = f"entry:{code.code}"
                redis_client.delete(redis_key)

            db.commit()

        logger.info("Cleaned up expired codes", count=len(expired_codes))
        return {"cleaned_count": len(expired_codes)}

    except Exception as e:
        logger.error("Failed to cleanup expired codes", error=str(e))

        # Retry if not exceeded max retries
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60 * (2 ** self.request.retries))

        return {"error": str(e)}


@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_entry_codes(self):
    """Clean up expired entry codes"""
    try:
        with SessionLocal() as db:
            # Clean up expired codes from database
            result = db.execute(text("""
                                     DELETE
                                     FROM entry_codes_new
                                     WHERE expires_at < NOW()
                                       AND status = 'active'
                                     """))

            db.commit()

            # Clean up expired codes from Redis
            expired_keys = []
            for key in redis_client.scan_iter(match="entry_code:*"):
                ttl = redis_client.ttl(key)
                if ttl == -1:  # Key exists but no TTL set
                    redis_client.delete(key)
                    expired_keys.append(key)
                elif ttl == -2:  # Key doesn't exist
                    expired_keys.append(key)

            logger.info(f"Cleaned up {result.rowcount} expired entry codes from DB and {len(expired_keys)} from Redis")

    except Exception as e:
        logger.error(f"Failed to cleanup expired entry codes: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3)
def process_entry_granted(self, tenant_id: str, user_id: str, code: str):
    """Process entry granted event"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process entry granted logic here
            logger.info(f"Processing entry granted for tenant {tenant_id}, user {user_id}, code {code}")

            # Update metrics
            entry_operations_total.labels(operation="granted", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process entry granted: {e}")
        entry_operations_total.labels(operation="granted", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_entry_denied(self, tenant_id: str, user_id: str, code: str, reason: str):
    """Process entry denied event"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process entry denied logic here
            logger.info(f"Processing entry denied for tenant {tenant_id}, user {user_id}, code {code}, reason {reason}")

            # Update metrics
            entry_operations_total.labels(operation="denied", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process entry denied: {e}")
        entry_operations_total.labels(operation="denied", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

# =============================================================================
# EVENT CONSUMPTION WORKERS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_tenant_created(self, tenant_id: str, tenant_data: Dict[str, Any]):
    """Process TENANT_CREATED events for Entry service"""
    try:
        logger.info(f"Processing TENANT_CREATED for Entry service tenant: {tenant_id}")

        # Create default entry configurations for new tenant
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Create default entry configurations
            default_configs = [
                {
                    "tenant_id": tenant_id,
                    "config_name": "standard_entry",
                    "config_type": "entry_rules",
                    "config_data": {
                        "require_approval": False,
                        "max_entries_per_day": 100,
                        "entry_timeout_minutes": 30
                    }
                }
            ]

            for config_data in default_configs:
                # Check if config already exists
                existing = db.execute(text("""
                    SELECT 1 FROM entry_configs
                    WHERE tenant_id = :tenant_id AND config_name = :config_name
                """), {
                    "tenant_id": config_data["tenant_id"],
                    "config_name": config_data["config_name"]
                }).fetchone()

                if not existing:
                    # Create new entry configuration
                    db.execute(text("""
                        INSERT INTO entry_configs (tenant_id, config_name, config_type, config_data)
                        VALUES (:tenant_id, :config_name, :config_type, :config_data)
                    """), {
                        "tenant_id": config_data["tenant_id"],
                        "config_name": config_data["config_name"],
                        "config_type": config_data["config_type"],
                        "config_data": json.dumps(config_data["config_data"])
                    })

            db.commit()
            logger.info(f"Created default entry configurations for tenant: {tenant_id}")

    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED for Entry service {tenant_id}: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_order_completed(self, order_id: str, order_data: Dict[str, Any]):
    """Process ORDER_COMPLETED events for Entry service"""
    try:
        logger.info(f"Processing ORDER_COMPLETED for Entry service order: {order_id}")

        # Check if order completion requires entry code generation
        with SessionLocal() as db:
            tenant_id = order_data.get("tenant_id")

            if tenant_id:
                set_rls_context(db, tenant_id)

            # Check if order has pickup requirements that need entry codes
            pickup_required = order_data.get("pickup_required", False)
            if pickup_required:
                # Generate entry code for order pickup
                entry_code = generate_entry_code()
                expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

                # Create entry code record
                db.execute(text("""
                    INSERT INTO entry_codes (tenant_id, code, order_id, expires_at, status, created_by)
                    VALUES (:tenant_id, :code, :order_id, :expires_at, 'active', 'system')
                """), {
                    "tenant_id": tenant_id,
                    "code": entry_code,
                    "order_id": order_id,
                    "expires_at": expires_at
                })

                db.commit()
                logger.info(f"Generated entry code {entry_code} for order pickup: {order_id}")

    except Exception as e:
        logger.error(f"Failed to process ORDER_COMPLETED for Entry service {order_id}: {e}")
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            result = db.execute(text("""
                DELETE FROM outbox_events
                WHERE status = 'published' AND processed_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} old Entry service outbox events")

    except Exception as e:
        logger.error(f"Failed to cleanup old Entry service outbox events: {e}")
        raise self.retry(exc=e, countdown=300)