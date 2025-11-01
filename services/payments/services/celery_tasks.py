# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_payment_intent(self, payment_intent_id: str, intent_data: Dict[str, Any]):
    """Process payment intent asynchronously"""
    try:
        with SessionLocal() as db:
            # Get payment intent
            intent = db.execute(text("""
                                     SELECT *
                                     FROM payment_intents_new
                                     WHERE id = :id
                                     """), {"id": payment_intent_id}).fetchone()

            if not intent:
                raise ValueError(f"Payment intent {payment_intent_id} not found")

            # Process payment logic here
            logger.info(f"Processing payment intent {payment_intent_id}")

            # Update status
            db.execute(text("""
                            UPDATE payment_intents_new
                            SET status     = 'processed',
                                updated_at = NOW()
                            WHERE id = :id
                            """), {"id": payment_intent_id})

            db.commit()

            # Update metrics
            payments_operations_total.labels(operation="intent", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process payment intent {payment_intent_id}: {e}")
        payments_operations_total.labels(operation="intent", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_payment_refund(self, payment_id: str, refund_data: Dict[str, Any]):
    """Process payment refund asynchronously"""
    try:
        with SessionLocal() as db:
            # Get payment
            payment = db.execute(text("""
                                      SELECT *
                                      FROM payments_new
                                      WHERE id = :id
                                      """), {"id": payment_id}).fetchone()

            if not payment:
                raise ValueError(f"Payment {payment_id} not found")

            # Process refund logic here
            logger.info(f"Processing payment refund for payment {payment_id}")

            # Update status
            db.execute(text("""
                            UPDATE payments_new
                            SET status     = 'refunded',
                                updated_at = NOW()
                            WHERE id = :id
                            """), {"id": payment_id})

            db.commit()

            # Update metrics
            payments_operations_total.labels(operation="refund", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process payment refund for payment {payment_id}: {e}")
        payments_operations_total.labels(operation="refund", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_payments(self):
    """Clean up old payments"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)

            # Clean up old payments
            payment_result = db.execute(text("""
                                             DELETE
                                             FROM payments_new
                                             WHERE created_at < :cutoff_date
                                               AND status IN ('completed', 'failed', 'refunded')
                                             """), {"cutoff_date": cutoff_date})

            # Clean up old payment intents
            intent_result = db.execute(text("""
                                            DELETE
                                            FROM payment_intents_new
                                            WHERE created_at < :cutoff_date
                                              AND status IN ('completed', 'failed')
                                            """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {payment_result.rowcount} old payments and {intent_result.rowcount} old payment intents")

    except Exception as e:
        logger.error(f"Failed to cleanup old payments: {e}")
        raise self.retry(exc=e, countdown=300)
# =============================================================================
# CELERY WORKERS - Event Consumption
# =============================================================================

@celery_app.task(bind=True, max_retries=3, name='payments.process_order_completed')
def process_order_completed(self, event_data: Dict[str, Any]):
    """Process ORDER_COMPLETED event from orders service"""
    try:
        tenant_id = event_data.get('tenant_id')
        order_id = event_data.get('order_id')
        total_amount = event_data.get('total_minor')

        if not all([tenant_id, order_id, total_amount]):
            logger.error('Missing required fields in ORDER_COMPLETED event')
            return {'status': 'error', 'message': 'Missing required fields'}

        with SessionLocal() as db:
            # Create payment intent for the order
            payment_intent_id = f"pi_{uuid.uuid4().hex[:12]}"

            payment_intent = PaymentTransactionNew(
                payment_intent_id=payment_intent_id,
                tenant_id=tenant_id,
                order_id=order_id,
                amount_minor=total_amount,
                currency='GBP',
                status='pending',
                provider='stripe',
                payment_method='card'
            )
            db.add(payment_intent)
            db.commit()

            logger.info(f"Created payment intent {payment_intent_id} for order {order_id}")

        return {'status': 'ok', 'payment_intent_id': payment_intent_id}

    except Exception as e:
        logger.error(f"Failed to process ORDER_COMPLETED event: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3, name='payments.cleanup_old_outbox_events')
def cleanup_outbox_events(self):
    """Clean up old outbox events"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            result = db.execute(
                text("DELETE FROM outbox_events WHERE created_at < :cutoff AND status IN ('published', 'failed')"),
                {'cutoff': cutoff}
            )
            db.commit()
            logger.info(f'Cleaned up {result.rowcount} old outbox events')
            return {'deleted': result.rowcount}

    except Exception as e:
        logger.error(f"Failed to cleanup outbox events: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3, name='payments.cleanup_old_payments')
def cleanup_old_payments(self):
    """Clean up old payment transactions and refunds"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=365)

            # Clean old transactions
            trans_result = db.execute(
                text(
                    "DELETE FROM payment_transactions_new WHERE created_at < :cutoff AND status IN ('failed', 'canceled')"),
                {'cutoff': cutoff}
            )

            # Clean old refunds
            refund_result = db.execute(
                text("DELETE FROM payment_refunds WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )

            db.commit()
            logger.info(f"Cleaned {trans_result.rowcount} old transactions and {refund_result.rowcount} old refunds")
            return {'transactions_deleted': trans_result.rowcount, 'refunds_deleted': refund_result.rowcount}

    except Exception as e:
        logger.error(f"Failed to cleanup old payments: {e}")
        raise self.retry(exc=e, countdown=300)