# ==================================================================================
# BACKGROUND JOBS FOR ESCALATION AND REMINDERS
# ==================================================================================
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_
from Models import ApprovalRequest, ApprovalRequestApprover, ApprovalChainStep
from core.db_config import SessionLocal
from utils.logger import logger

async def check_escalations():
    """Check and send escalations for pending approvals"""
    db = SessionLocal()
    try:
        # Find approvers where escalation is due
        now = datetime.now(timezone.utc)
        
        # Get all pending approvers with escalation configured
        # First get all pending approvers
        pending_approvers = db.query(ApprovalRequestApprover).join(
            ApprovalRequest, ApprovalRequestApprover.request_id == ApprovalRequest.request_id
        ).filter(
            ApprovalRequestApprover.status == "pending",
            ApprovalRequestApprover.escalation_sent == False,
            ApprovalRequest.request_status == "pending"
        ).all()
        
        for approver in pending_approvers:
            # Get the approval request
            approval_request = db.query(ApprovalRequest).filter(
                ApprovalRequest.request_id == approver.request_id
            ).first()
            
            if not approval_request:
                continue
            
            # Get the step to check escalation time
            step = db.query(ApprovalChainStep).filter(
                ApprovalChainStep.approval_chain_id == approval_request.chain_id,
                ApprovalChainStep.step_number == approver.step_number
            ).first()
            
            if step and step.escalation_after_hours:
                # Calculate when escalation should be sent
                escalation_time = approver.created_at + timedelta(hours=step.escalation_after_hours)
                
                if now >= escalation_time:
                    # Send escalation (implement notification logic)
                    await send_escalation_notification(approver, step)
                    
                    # Mark escalation as sent
                    approver.escalation_sent = True
                    db.commit()
                    
                    logger.info(f"📧 Escalation sent for approval request {approver.request_id}, step {approver.step_number}")
        
    except Exception as e:
        logger.error(f"❌ Escalation check failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

async def send_reminders():
    """Send reminders for pending approvals"""
    db = SessionLocal()
    try:
        # Find pending approvals older than 24 hours
        reminder_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        
        pending_approvers = db.query(ApprovalRequestApprover).join(
            ApprovalRequest, ApprovalRequestApprover.request_id == ApprovalRequest.request_id
        ).filter(
            ApprovalRequestApprover.status == "pending",
            ApprovalRequest.request_status == "pending",
            ApprovalRequestApprover.created_at < reminder_threshold
        ).all()
        
        for approver in pending_approvers:
            # Send reminder (implement notification logic)
            await send_reminder_notification(approver)
            
            logger.info(f"📬 Reminder sent for approval request {approver.request_id}")
        
    except Exception as e:
        logger.error(f"❌ Reminder check failed: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

async def send_escalation_notification(approver, step):
    """Send escalation notification (implement email/notification logic)"""
    # TODO: Implement notification sending (email, SMS, etc.)
    # For now, just log
    logger.info(f"📧 ESCALATION: Request {approver.request_id} needs attention at step {step.step_number}")

async def send_reminder_notification(approver):
    """Send reminder notification (implement email/notification logic)"""
    # TODO: Implement notification sending (email, SMS, etc.)
    # For now, just log
    logger.info(f"📬 REMINDER: Request {approver.request_id} is pending approval")

async def run_background_jobs():
    """Run all background jobs periodically"""
    while True:
        try:
            await check_escalations()
            await send_reminders()
            # Run every 15 minutes
            await asyncio.sleep(900)
        except Exception as e:
            logger.error(f"❌ Background job error: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 1 minute before retry

