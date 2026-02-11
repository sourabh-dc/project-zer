# services/background_jobs.py
"""
Background Jobs Service

Handles:
- Expiring approval requests
- Resetting approver limits
- Resetting recurring budgets
- Sending reminders for pending approvals
"""
import asyncio
import uuid
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import update
from core.db_config import SessionLocal
from Models import ApprovalRequest, ApprovalRequestApprover, InstantBudgetRequest, ApproverLimit, UserCostCentre, SpendingEvent
from utils.logger import logger


async def expire_approval_requests():
    """Mark expired approval requests as expired"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        result = db.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.request_status == "pending",
                ApprovalRequest.expires_at.isnot(None),
                ApprovalRequest.expires_at < now
            )
            .values(request_status="expired", completed_date=now)
        )
        db.commit()
        if result.rowcount > 0:
            logger.info(f"✅ Expired {result.rowcount} approval requests")
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error expiring approval requests: {e}")
    finally:
        db.close()


async def check_reminders():
    """Check for approval requests that need reminders (24 hours pending)"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        reminder_time = now - timedelta(hours=24)
        
        # Find pending approvers older than 24 hours
        pending_approvers = db.query(ApprovalRequestApprover).filter(
            ApprovalRequestApprover.status == "pending",
            ApprovalRequestApprover.created_at < reminder_time
        ).all()
        
        for approver in pending_approvers:
            # TODO: Send actual reminder notification
            logger.info(f"📧 Reminder needed for approval request {approver.request_id}, approver {approver.approver_user_id}")
        
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
    """Reset approver limits based on their reset period"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        
        limits = db.query(ApproverLimit).all()
        reset_count = 0
        
        for lim in limits:
            should_reset = False
            
            if lim.reset_period == "daily":
                should_reset = (not lim.last_reset_at) or (lim.last_reset_at.date() < today)
            elif lim.reset_period == "weekly":
                should_reset = (not lim.last_reset_at) or (lim.last_reset_at.isocalendar()[1] != now.isocalendar()[1])
            elif lim.reset_period == "monthly":
                should_reset = (not lim.last_reset_at) or ((lim.last_reset_at.year, lim.last_reset_at.month) != (now.year, now.month))
            
            if should_reset:
                lim.consumed_amount_minor = 0
                lim.last_reset_at = now
                reset_count += 1
        
        db.commit()
        
        if reset_count > 0:
            logger.info(f"✅ Reset limits for {reset_count} approvers")
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


async def reset_recurring_budgets():
    """Reset recurring budgets (daily/weekly/monthly/yearly)"""
    db = SessionLocal()
    try:
        today = date.today()
        
        # Find all user cost centres with recurring budgets that need reset
        budgets_to_reset = db.query(UserCostCentre).filter(
            UserCostCentre.recurring_period != "none",
            UserCostCentre.next_reset_date <= today
        ).all()
        
        for uc in budgets_to_reset:
            # Reset spent amount to 0
            old_spent = uc.spent_minor
            uc.spent_minor = 0
            
            # Allocate new recurring budget
            uc.allocated_budget_minor = uc.recurring_budget_minor
            
            # Update reset dates
            uc.last_reset_date = today
            if uc.recurring_period == "daily":
                uc.next_reset_date = today + timedelta(days=1)
            elif uc.recurring_period == "weekly":
                uc.next_reset_date = today + timedelta(days=7)
            elif uc.recurring_period == "monthly":
                next_month = today.month + 1 if today.month < 12 else 1
                next_year = today.year if today.month < 12 else today.year + 1
                uc.next_reset_date = date(next_year, next_month, 1)
            elif uc.recurring_period == "yearly":
                uc.next_reset_date = date(today.year + 1, 1, 1)
            
            # Record spending event for audit
            spending_event = SpendingEvent(
                event_id=uuid.uuid4(),
                event_type="budget_reset",
                user_id=uc.user_id,
                cost_centre_id=uc.cost_centre_id,
                order_id=None,
                approval_request_id=None,
                amount_minor=uc.recurring_budget_minor,
                currency_code=uc.currency_code,
                event_metadata={
                    "recurring_period": uc.recurring_period,
                    "previous_spent": old_spent,
                    "new_allocated": uc.recurring_budget_minor
                }
            )
            db.add(spending_event)
            
            logger.info(f"✅ Reset recurring budget for user {uc.user_id}: £{uc.recurring_budget_minor / 100:.2f} ({uc.recurring_period})")
        
        db.commit()
        
        if len(budgets_to_reset) > 0:
            logger.info(f"✅ Reset {len(budgets_to_reset)} recurring budgets")
            
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error resetting recurring budgets: {e}")
    finally:
        db.close()


async def run_background_jobs():
    """Run all background jobs"""
    logger.info("🚀 Starting all background jobs...")
    
    # Approval expiry and reminders (runs every hour)
    async def approval_jobs_loop():
        while True:
            try:
                await expire_approval_requests()
                await check_reminders()
            except Exception as e:
                logger.error(f"❌ Approval background job error: {e}")
            await asyncio.sleep(3600)  # Run every hour
    
    # Recurring budget reset (runs every hour)
    async def recurring_budget_loop():
        while True:
            try:
                await reset_recurring_budgets()
            except Exception as e:
                logger.error(f"❌ Recurring budget reset error: {e}")
            await asyncio.sleep(3600)  # Run every hour
    
    # Start instant budget worker (runs every 10 seconds)
    asyncio.create_task(instant_worker())
    
    # Start approval jobs loop
    asyncio.create_task(approval_jobs_loop())
    
    # Start recurring budget loop
    asyncio.create_task(recurring_budget_loop())
    
    logger.info("✅ All background jobs started")
