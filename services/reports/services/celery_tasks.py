from sqlalchemy import text
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from ..core.celery_config import celery_app
from ..repositories.db_config import SessionLocal
from ..models import ReportJob
from ..utils.metrics import report_requests_total
from ..utils.reports_logger import logger
# =============================================================================
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_report_generation(self, job_id: str, report_type: str, parameters: Dict[str, Any]):
    """Process report generation asynchronously"""
    try:
        with SessionLocal() as db:
            # Get report job
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if not job:
                raise ValueError(f"Report job {job_id} not found")

            # Process report generation logic here
            logger.info(f"Processing report generation for job {job_id}, type {report_type}")

            # Update metrics
            report_requests_total.labels(report_type=report_type, status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process report generation for job {job_id}: {e}")
        report_requests_total.labels(report_type=report_type, status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_data_aggregation(self, tenant_id: str, aggregation_data: Dict[str, Any]):
    """Process data aggregation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context (best-effort)
            try:
                db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            except Exception:
                pass

            # Process data aggregation logic here
            logger.info(f"Processing data aggregation for tenant {tenant_id}")

            # Update metrics
            report_requests_total.labels(report_type="data_aggregation", status="success").inc()

    except Exception as e:
        logger.error(f"Failed to process data aggregation for tenant {tenant_id}: {e}")
        report_requests_total.labels(report_type="data_aggregation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def cleanup_old_reports(self):
    """Clean up old reports"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

            # Clean up old report jobs
            job_result = db.execute(text("""
                                         DELETE
                                         FROM report_jobs_new
                                         WHERE created_at < :cutoff_date
                                           AND status IN ('completed', 'failed')
                                         """), {"cutoff_date": cutoff_date})

            # Clean up old report data
            data_result = db.execute(text("""
                                          DELETE
                                          FROM report_data_new
                                          WHERE created_at < :cutoff_date
                                          """), {"cutoff_date": cutoff_date})

            db.commit()

            logger.info(f"Cleaned up {job_result.rowcount} old report jobs and {data_result.rowcount} old report data")

    except Exception as e:
        logger.error(f"Failed to cleanup old reports: {e}")
        raise self.retry(exc=e, countdown=300)