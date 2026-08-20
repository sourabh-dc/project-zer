"""
Scheduled sync — APScheduler in-process (per plan decision).

Jobs are loaded from tenant_connections.schedule_cron at startup and
refreshed whenever a connection is saved. Each job opens its own DB
session so long-running syncs never hold a request session.
"""
from __future__ import annotations

import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from provisioning_service.Models import TenantConnection
from provisioning_service.core.db_config import SessionLocal
from provisioning_service.utils.logger import logger

scheduler = AsyncIOScheduler()

_JOB_PREFIX = "conn-sync-"


def _run_connection_sync(connection_id: str) -> None:
    """Execute one scheduled sync in a fresh session (threadpool job)."""
    from provisioning_service.core.connectors.engine import run_sync

    db = SessionLocal()
    try:
        connection = db.query(TenantConnection).filter(
            TenantConnection.connection_id == uuid.UUID(connection_id),
            TenantConnection.status == "active",
        ).first()
        if not connection:
            logger.warning(f"Scheduled sync skipped — connection {connection_id} not active")
            return
        run_sync(db, connection, trigger="scheduled")
    except Exception as e:
        logger.error(f"Scheduled sync failed for connection {connection_id}: {e}")
    finally:
        db.close()


def schedule_connection(connection: TenantConnection) -> None:
    """(Re)create the cron job for a connection, or remove it."""
    job_id = f"{_JOB_PREFIX}{connection.connection_id}"
    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None

    if connection.schedule_cron and connection.status == "active":
        try:
            trigger = CronTrigger.from_crontab(connection.schedule_cron)
        except ValueError:
            logger.error(f"Invalid cron on connection {connection.connection_id}: {connection.schedule_cron!r}")
            return
        scheduler.add_job(
            _run_connection_sync,
            trigger=trigger,
            args=[str(connection.connection_id)],
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"Scheduled connection {connection.connection_id} at '{connection.schedule_cron}'")


def unschedule_connection(connection_id) -> None:
    job_id = f"{_JOB_PREFIX}{connection_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def _run_plan_change_sweep() -> None:
    """Apply scheduled downgrades whose billing period has ended."""
    from provisioning_service.services.subscriptions_routes import apply_due_plan_changes

    db = SessionLocal()
    try:
        applied = apply_due_plan_changes(db)
        if applied:
            logger.info(f"Plan-change sweep applied {applied} pending downgrade(s)")
    except Exception as e:
        logger.error(f"Plan-change sweep failed: {e}")
    finally:
        db.close()


def load_schedules() -> int:
    """Load all cron-enabled connections at startup. Returns job count."""
    db = SessionLocal()
    try:
        connections = db.query(TenantConnection).filter(
            TenantConnection.schedule_cron.isnot(None),
            TenantConnection.status == "active",
        ).all()
        for conn in connections:
            schedule_connection(conn)
        return len(connections)
    finally:
        db.close()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        # Daily sweep at 00:30 UTC: apply due plan downgrades (fallback for
        # non-Stripe subs; Stripe subs are handled by the invoice.paid webhook)
        scheduler.add_job(
            _run_plan_change_sweep,
            trigger=CronTrigger.from_crontab("30 0 * * *"),
            id="plan-change-sweep",
            replace_existing=True,
            max_instances=1,
        )
        count = load_schedules()
        logger.info(f"✅ Connector scheduler started — {count} scheduled connections")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Connector scheduler stopped")
