from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from sqlalchemy import text

from ..core.celery_config import celery_app
from ..repositories.db_config import SessionLocal
from ..models import ApprovalRequest, ApprovalChain
from ..utils.approvals_logger import logger
from ..utils.metrics import approval_requests_total


# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_approval_request(self, approval_id: str):
    """Process approval request asynchronously"""
    try:
        with SessionLocal() as db:
            # Get approval request
            approval = db.execute(text("""
                                       SELECT *
                                       FROM approval_requests_new
                                       WHERE id = :id
                                       """), {"id": approval_id}).fetchone()

            if not approval:
                raise ValueError(f"Approval request {approval_id} not found")

            # Process approval logic here
            logger.info(f"Processing approval request {approval_id}")

            # Update status
            db.execute(text("""
                            UPDATE approval_requests_new
                            SET status     = 'processed',
                                updated_at = NOW()
                            WHERE id = :id
                            """), {"id": approval_id})

            db.commit()

            # Update metrics
            approval_requests_total.labels(operation="process", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process approval request {approval_id}: {e}")
        approval_requests_total.labels(operation="process", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_approvals(self):
    """Clean up old approval requests"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)

            result = db.execute(text("""
                                     DELETE
                                     FROM approval_requests_new
                                     WHERE created_at < :cutoff_date
                                       AND status IN ('approved', 'rejected')
                                     """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} old approval requests")

    except Exception as e:
        logger.error(f"Failed to cleanup old approvals: {e}")
        raise self.retry(exc=e, countdown=300)


# =============================================================================
# EVENT CONSUMPTION WORKERS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_tenant_created(self, tenant_id: str, tenant_data: Dict[str, Any]):
    """Process TENANT_CREATED events"""
    try:
        logger.info(f"Processing TENANT_CREATED for tenant: {tenant_id}")

        # Create default approval chains for new tenant
        with SessionLocal() as db:
            # Create default approval chains for common scenarios
            default_chains = [
                {
                    "name": "Purchase Order Approval",
                    "description": "Standard purchase order approval workflow",
                    "chain_type": "purchase_order",
                    "tenant_id": tenant_id
                },
                {
                    "name": "Budget Approval",
                    "description": "Budget increase approval workflow",
                    "chain_type": "budget",
                    "tenant_id": tenant_id
                },
                {
                    "name": "Vendor Onboarding",
                    "description": "New vendor approval workflow",
                    "chain_type": "vendor_onboarding",
                    "tenant_id": tenant_id
                }
            ]

            for chain_data in default_chains:
                chain = ApprovalChain(**chain_data)
                db.add(chain)

            db.commit()
            logger.info(f"Created default approval chains for tenant: {tenant_id}")

    except Exception as e:
        logger.error(f"Failed to process TENANT_CREATED for {tenant_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_order_completed(self, order_id: str, order_data: Dict[str, Any]):
    """Process ORDER_COMPLETED events"""
    try:
        logger.info(f"Processing ORDER_COMPLETED for order: {order_id}")

        # Check if order requires approval based on amount or type
        with SessionLocal() as db:
            # This could trigger approval chains for high-value orders
            order_amount = order_data.get("total_amount", 0)
            tenant_id = order_data.get("tenant_id")

            if order_amount > 10000:  # Example threshold
                # Create approval request for high-value order
                approval_request = ApprovalRequest(
                    request_type="order_review",
                    title=f"High-value order review: {order_id}",
                    description=f"Order amount: ${order_amount}",
                    requested_by=order_data.get("user_id", "system"),
                    tenant_id=tenant_id,
                    metadata={"order_id": order_id, "amount": order_amount}
                )
                db.add(approval_request)
                db.commit()

                logger.info(f"Created approval request for high-value order: {order_id}")

    except Exception as e:
        logger.error(f"Failed to process ORDER_COMPLETED for {order_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            result = db.execute(text("""
                                     DELETE
                                     FROM outbox_events
                                     WHERE status = 'published'
                                       AND processed_at < :cutoff_date
                                     """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} old outbox events")

    except Exception as e:
        logger.error(f"Failed to cleanup old outbox events: {e}")
        raise self.retry(exc=e, countdown=300)