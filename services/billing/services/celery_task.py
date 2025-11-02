from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import text

from ..core.celery_config import celery_app
from ..repositories.db_config import SessionLocal, set_rls_context
from ..utils.billing_logger import logger
from ..utils.metrics import billing_operations_total
from ..utils.rabbitmq import publish_to_rabbitmq

# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_billing_cycle(self, tenant_id: str, cycle_date: str):
    """Process billing cycle for a tenant"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Get cycle date
            cycle_dt = datetime.fromisoformat(cycle_date.replace('Z', '+00:00'))

            # Process billing logic here
            logger.info(f"Processing billing cycle for tenant {tenant_id} on {cycle_date}")

            # Update metrics
            billing_operations_total.labels(operation="cycle", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process billing cycle for tenant {tenant_id}: {e}")
        billing_operations_total.labels(operation="cycle", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_settlement_payout(self, settlement_id: str):
    """Process settlement payout"""
    try:
        with SessionLocal() as db:
            # Get settlement
            settlement = db.execute(text("""
                                         SELECT *
                                         FROM settlements_new
                                         WHERE id = :id
                                         """), {"id": settlement_id}).fetchone()

            if not settlement:
                raise ValueError(f"Settlement {settlement_id} not found")

            # Process payout logic here
            logger.info(f"Processing settlement payout {settlement_id}")

            # Update status
            db.execute(text("""
                            UPDATE settlements_new
                            SET status     = 'paid',
                                updated_at = NOW()
                            WHERE id = :id
                            """), {"id": settlement_id})

            db.commit()

            # Update metrics
            billing_operations_total.labels(operation="payout", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process settlement payout {settlement_id}: {e}")
        billing_operations_total.labels(operation="payout", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_approval_resolved(self, approval_id: str, approval_data: Dict[str, Any]):
    """Process APPROVAL_RESOLVED events from Approvals service"""
    try:
        logger.info(f"Processing APPROVAL_RESOLVED for approval: {approval_id}")

        with SessionLocal() as db:
            # Set RLS context for the tenant
            tenant_id = approval_data.get("tenant_id")
            if tenant_id:
                set_rls_context(db, tenant_id)

            # Check if this approval affects any pending settlements
            approval_type = approval_data.get("request_type")
            if approval_type == "settlement_approval":
                # Update settlement status based on approval decision
                settlement_id = approval_data.get("metadata", {}).get("settlement_id")
                if settlement_id:
                    approved = approval_data.get("status") == "approved"

                    if approved:
                        # Mark settlement as approved and ready for payout
                        db.execute(text("""
                                        UPDATE settlements_new
                                        SET status      = 'approved',
                                            approved_at = NOW(),
                                            approved_by = :user_id
                                        WHERE id = :settlement_id
                                          AND status = 'pending'
                                        """), {
                                       "settlement_id": settlement_id,
                                       "user_id": approval_data.get("approved_by")
                                   })

                        # Publish settlement approved event
                        publish_to_rabbitmq("SETTLEMENT_APPROVED", {
                            "settlement_id": settlement_id,
                            "tenant_id": tenant_id,
                            "approved_by": approval_data.get("approved_by")
                        }, tenant_id)

                        logger.info(f"Settlement {settlement_id} approved")
                    else:
                        # Mark settlement as rejected
                        db.execute(text("""
                                        UPDATE settlements_new
                                        SET status      = 'rejected',
                                            rejected_at = NOW(),
                                            rejected_by = :user_id
                                        WHERE id = :settlement_id
                                          AND status = 'pending'
                                        """), {
                                       "settlement_id": settlement_id,
                                       "user_id": approval_data.get("approved_by")
                                   })

                        logger.info(f"Settlement {settlement_id} rejected")

                    db.commit()

    except Exception as e:
        logger.error(f"Failed to process APPROVAL_RESOLVED for {approval_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            result = db.execute(text("""
                                     DELETE
                                     FROM billing_outbox_events
                                     WHERE status = 'published'
                                       AND processed_at < :cutoff_date
                                     """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {result.rowcount} old billing outbox events")

    except Exception as e:
        logger.error(f"Failed to cleanup old billing outbox events: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_billing_data(self):
    """Clean up old billing data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)

            # Clean up old invoices
            invoice_result = db.execute(text("""
                                             DELETE
                                             FROM invoices_new
                                             WHERE created_at < :cutoff_date
                                               AND status IN ('paid', 'cancelled')
                                             """), {"cutoff_date": cutoff_date})

            # Clean up old settlements
            settlement_result = db.execute(text("""
                                                DELETE
                                                FROM settlements_new
                                                WHERE created_at < :cutoff_date
                                                  AND status IN ('paid', 'cancelled')
                                                """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {invoice_result.rowcount} old invoices and {settlement_result.rowcount} old settlements")

    except Exception as e:
        logger.error(f"Failed to cleanup old billing data: {e}")
        raise self.retry(exc=e, countdown=300)