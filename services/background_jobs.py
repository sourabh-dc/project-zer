# services/background_jobs.py
import asyncio
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import update
from core.db_config import SessionLocal
from Models import ApprovalRequest, ApprovalRequestApprover, ApprovalChainStep, InstantBudgetRequest, ApproverLimit
from utils.logger import logger

async def check_escalations():
    """Check for approval requests that need escalation"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        steps = db.query(ApprovalChainStep).filter(
            ApprovalChainStep.escalation_after_hours.isnot(None)
        ).all()
        
        for step in steps:
            escalation_time = now - timedelta(hours=step.escalation_after_hours)
            pending_approvers = db.query(ApprovalRequestApprover).filter(
                ApprovalRequestApprover.step_number == step.step_number,
                ApprovalRequestApprover.status == "pending",
                ApprovalRequestApprover.created_at < escalation_time,
                ApprovalRequestApprover.escalation_sent == False
            ).all()
            
            for approver in pending_approvers:
                approver.escalation_sent = True
                logger.info(f"⚠️ Escalation sent for approval request {approver.request_id}, step {step.step_number}")
        
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Escalation check failed: {e}")
    finally:
        db.close()

async def check_reminders():
    """Check for approval requests that need reminders"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        reminder_time = now - timedelta(hours=24)  # Send reminder after 24 hours
        
        pending_approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.status == "pending",
            ApprovalRequestApprover.created_at < reminder_time,
            ApprovalRequestApprover.reminder_sent == False
        ).all()
        
        for approver in pending_approvers:
            approver.reminder_sent = True
            logger.info(f"📧 Reminder sent for approval request {approver.request_id}")
        
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Reminder check failed: {e}")
    finally:
        db.close()

async def expire_instant_budget_requests():
    """Mark expired instant budget requests as expired"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        result = db.execute(
            update(InstantBudgetRequest)
            .where(
                InstantBudgetRequest.status == "pending",
                InstantBudgetRequest.expires_at < now
            )
            .values(status="expired")
        )
        db.commit()
        if result.rowcount > 0:
            logger.info(f"✅ Expired {result.rowcount} instant budget requests")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error expiring instant budget requests: {e}")
    finally:
        db.close()

async def reset_approver_limits():
    """Reset daily and monthly approver limits"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        current_month_start = date(now.year, now.month, 1)
        
        # Reset daily limits
        daily_result = db.execute(
            update(ApproverLimit)
            .where(ApproverLimit.last_reset_daily < today)
            .values(daily_spent_minor=0, last_reset_daily=today)
        )
        
        # Reset monthly limits
        monthly_result = db.execute(
            update(ApproverLimit)
            .where(ApproverLimit.last_reset_monthly < current_month_start)
            .values(monthly_spent_minor=0, last_reset_monthly=current_month_start)
        )
        
        db.commit()
        
        if daily_result.rowcount > 0:
            logger.info(f"✅ Reset daily limits for {daily_result.rowcount} approvers")
        if monthly_result.rowcount > 0:
            logger.info(f"✅ Reset monthly limits for {monthly_result.rowcount} approvers")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error resetting approver limits: {e}")
    finally:
        db.close()

async def instant_worker():
    """Background worker for instant budget jobs"""
    logger.info("🚀 Starting instant budget background worker...")
    while True:
        try:
            await expire_instant_budget_requests()
            await reset_approver_limits()
        except Exception as e:
            logger.error(f"❌ Instant worker error: {e}")
        
        # Run every 10 seconds
        await asyncio.sleep(10)

async def run_background_jobs():
    """Run all background jobs"""
    logger.info("🚀 Starting all background jobs...")
    
    # Start approval escalations and reminders (runs every hour)
    async def approval_jobs_loop():
        while True:
            try:
                await check_escalations()
                await check_reminders()
            except Exception as e:
                logger.error(f"❌ Approval background job error: {e}")
            await asyncio.sleep(3600)  # Run every hour
    
    # Start instant budget worker (runs every 10 seconds)
    asyncio.create_task(instant_worker())
    
    # Start approval jobs loop
    asyncio.create_task(approval_jobs_loop())
    
    logger.info("✅ All background jobs started")
