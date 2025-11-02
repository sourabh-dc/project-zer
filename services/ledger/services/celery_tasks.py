# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_journal_entry(self, tenant_id: str, entry_data: Dict[str, Any]):
    """Process journal entry asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process journal entry logic here
            logger.info(f"Processing journal entry for tenant {tenant_id}")

            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="journal", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process journal entry for tenant {tenant_id}: {e}")
        ledger_requests_total.labels(method="POST", endpoint="journal", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_account_reconciliation(self, tenant_id: str, account_id: str):
    """Process account reconciliation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context
            set_rls_context(db, tenant_id)

            # Process reconciliation logic here
            logger.info(f"Processing account reconciliation for tenant {tenant_id}, account {account_id}")

            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="reconciliation", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process account reconciliation: {e}")
        ledger_requests_total.labels(method="POST", endpoint="reconciliation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_ledger_data(self):
    """Clean up old ledger data"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=365)

            # Clean up old journal entries
            journal_result = db.execute(text("""
                                             DELETE
                                             FROM journal_entries_new
                                             WHERE created_at < :cutoff_date
                                               AND status IN ('posted', 'cancelled')
                                             """), {"cutoff_date": cutoff_date})

            # Clean up old account balances
            balance_result = db.execute(text("""
                                             DELETE
                                             FROM account_balances_new
                                             WHERE created_at < :cutoff_date
                                               AND status = 'closed'
                                             """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(
                f"Cleaned up {journal_result.rowcount} old journal entries and {balance_result.rowcount} old account balances")

    except Exception as e:
        logger.error(f"Failed to cleanup old ledger data: {e}")
        raise self.retry(exc=e, countdown=300)


@celery_app.task(bind=True, max_retries=3)
def cleanup_expired_idempotency_records_task(self):
    """Clean up expired idempotency records"""
    try:
        with SessionLocal() as db:
            expired_count = cleanup_expired_idempotency_records(db)

            if expired_count > 0:
                ledger_idempotency_cleanup_total.inc(expired_count)
                logger.info(f"Cleaned up {expired_count} expired idempotency records")

            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="cleanup", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to cleanup expired idempotency records: {e}")
        ledger_requests_total.labels(method="POST", endpoint="cleanup", status="error").inc()
        raise self.retry(exc=e, countdown=300)

# Celery Beat Tasks for Daily Rollups
@celery_app.task(bind=True, max_retries=3)
def generate_daily_ledger_rollups(self, date_str: str = None):
    """Generate daily rollups for ledger entries"""
    try:
        # Default to yesterday if no date provided
        if date_str:
            target_date = datetime.fromisoformat(date_str).date()
        else:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        with SessionLocal() as db:
            rollup_manager = DailyRollupManager(db)

            # Generate ledger rollups
            rollup_data = rollup_manager.create_daily_ledger_rollup(target_date)

            # Generate tenant metrics
            metrics_data = rollup_manager.create_daily_tenant_metrics(target_date)

            # Generate API metrics
            api_data = rollup_manager.create_daily_api_metrics(target_date)

            # Store rollup data (in production, these would go to dedicated rollup tables)
            logger.info(f"Generated rollups for {target_date}: {len(rollup_data)} ledger, {len(metrics_data)} tenant, {len(api_data)} API metrics")

            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="rollups", status="success").inc()
            ledger_daily_rollups_total.labels(rollup_type="ledger", status="success").inc()
            ledger_daily_rollups_total.labels(rollup_type="tenant", status="success").inc()
            ledger_daily_rollups_total.labels(rollup_type="api", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to generate daily rollups: {e}")
        ledger_requests_total.labels(method="POST", endpoint="rollups", status="error").inc()
        raise self.retry(exc=e, countdown=3600)  # Retry in 1 hour

@celery_app.task(bind=True, max_retries=3)
def generate_daily_financial_reports(self, date_str: str = None):
    """Generate daily financial reports and summaries"""
    try:
        if date_str:
            target_date = datetime.fromisoformat(date_str).date()
        else:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        with SessionLocal() as db:
            # Generate P&L summary
            pnl_data = generate_pnl_summary(db, target_date)

            # Generate cash flow summary
            cash_flow_data = generate_cash_flow_summary(db, target_date)

            # Generate compliance summary
            compliance_data = generate_compliance_summary(db, target_date)

            logger.info(f"Generated financial reports for {target_date}")

    except Exception as e:
        logger.error(f"Failed to generate daily financial reports: {e}")
        raise self.retry(exc=e, countdown=3600)

# Celery Beat Configuration
from celery.schedules import crontab

# Configure Celery Beat schedule
celery_app.conf.beat_schedule = {
    'daily-ledger-rollups': {
        'task': 'services.ledger.main.generate_daily_ledger_rollups',
        'schedule': crontab(hour=2, minute=0),  # Run at 2 AM daily
    },
    'daily-financial-reports': {
        'task': 'services.ledger.main.generate_daily_financial_reports',
        'schedule': crontab(hour=3, minute=0),  # Run at 3 AM daily
    },
    'cleanup-idempotency-records': {
        'task': 'services.ledger.main.cleanup_expired_idempotency_records_task',
        'schedule': crontab(hour=1, minute=0),  # Run at 1 AM daily
    },
}

celery_app.conf.timezone = 'UTC'

@celery_app.task(bind=True, max_retries=3)
def process_usage_metering(self, date_str: str = None):
    """Process usage metering from ledger entries"""
    try:
        if date_str:
            target_date = datetime.fromisoformat(date_str).date()
        else:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        start_of_day = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)

        with SessionLocal() as db:
            usage_manager = UsageMeteringManager(db)
            usage_events = usage_manager.process_ledger_entries_for_usage(start_of_day, end_of_day)

            # In production, these would be sent to the Usage service
            if usage_events:
                logger.info(f"Generated {len(usage_events)} usage events for {target_date}")

                # Send to usage service (mock implementation)
                for event in usage_events:
                    # In production: send to actual usage service
                    # await send_to_usage_service(event)
                    # For now, just log the event
                    logger.info(f"Usage event: {event['meter_code']} - {event['quantity']} for tenant {event['tenant_id']}")
                    # Update usage event metrics
                    ledger_usage_events_total.labels(meter_code=event['meter_code'], status="generated").inc()

            # Update metrics
            ledger_requests_total.labels(method="POST", endpoint="usage", status="success").inc()
            ledger_usage_processing_total.labels(status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process usage metering: {e}")
        ledger_requests_total.labels(method="POST", endpoint="usage", status="error").inc()
        ledger_usage_processing_total.labels(status="error").inc()
        raise self.retry(exc=e, countdown=1800)  # Retry in 30 minutes

# Add usage metering to beat schedule
celery_app.conf.beat_schedule['daily-usage-metering'] = {
    'task': 'services.ledger.main.process_usage_metering',
    'schedule': crontab(hour=4, minute=0),  # Run at 4 AM daily
}