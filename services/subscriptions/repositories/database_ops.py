from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.subscriptions.models import OutboxEvent, AuditLog, Feature, SubscriptionPlan, PlanFeature, \
    TenantSubscription


def store_outbox_event(db: Session, event_type: str, tenant_id: str, aggregate_id: Optional[str] = None, event_data: Dict[str, Any] = {}):
    outbox_event = OutboxEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        aggregate_id=aggregate_id or tenant_id,
        event_data=event_data,
        status="pending",
        retry_count=0
    )
    db.add(outbox_event)
    db.commit()
    return str(outbox_event.id)

# Audit Logging
def audit_log(db: Session, tenant_id: str, user_id: Optional[str], action: str, resource_type: str, resource_id: Optional[str], details: Optional[Dict] = None, ip_address: Optional[str] = None, user_agent: Optional[str] = None):
    audit_entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    db.add(audit_entry)
    db.commit()


def create_feature_db(feature_data: Dict, db: Session)-> Dict:
    feature = Feature(
        code=feature_data["code"],
        name=feature_data["name"],
        description=feature_data.get("description"),
        category=feature_data.get("category"),
        active=True
    )
    db.add(feature)
    db.commit()
    db.refresh(feature)

    return {
        "feature_id": str(feature.id),
        "code": feature.code,
        "name": feature.name,
        "created": True
    }

def create_plan_db(req, db: Session) -> Dict:
    plan = SubscriptionPlan(
        code=req.code,
        name=req.name,
        description=req.description,
        price_yearly_minor=req.price_yearly_minor,
        currency=req.currency,
        active=True
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    return {
        "plan_id": str(plan.id),
        "code": plan.code,
        "name": plan.name,
        "created": True
    }

def add_feature_to_plan_db(plan_code: str, feature_code: str, limits: Optional[Dict], db: Session, user_context: Dict) -> Dict:
    # Check if plan and feature exist
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.code == plan_code).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    feature = db.query(Feature).filter(Feature.code == feature_code).first()
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    # Check if association already exists
    existing = db.query(PlanFeature).filter(
        PlanFeature.plan_code == plan_code,
        PlanFeature.feature_code == feature_code
    ).first()

    if existing:
        # Update existing association
        existing.enabled = True
        existing.limits = limits or {}
        db.commit()
        action = "UPDATE"
    else:
        # Create new association
        plan_feature = PlanFeature(
            plan_code=plan_code,
            feature_code=feature_code,
            enabled=True,
            limits=limits or {}
        )
        db.add(plan_feature)
        db.commit()
        action = "CREATE"

    audit_log(db, user_context.get("tenant_id"), user_context.get("user_id"), action, "plan_feature",
              f"{plan_code}:{feature_code}", {"limits": limits})

    return {
        "plan_code": plan_code,
        "feature_code": feature_code,
        "limits": limits,
        "action": action.lower()
    }

def remove_feature_from_plan_db(plan_code: str, feature_code: str, db: Session, user_context: Dict) -> Dict:

    plan_feature = db.query(PlanFeature).filter(
        PlanFeature.plan_code == plan_code,
        PlanFeature.feature_code == feature_code
    ).first()

    if not plan_feature:
        raise HTTPException(status_code=404, detail="Feature not associated with plan")

    plan_feature.enabled = False
    db.commit()

    audit_log(db, user_context.get("tenant_id"), user_context.get("user_id"), "DELETE", "plan_feature",
              f"{plan_code}:{feature_code}", {})

    return {"removed": True}

def renew_subscription_db(tenant_id: str, payment_method: str, db: Session, user_context) -> Dict:
    subscription = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Update subscription period
    subscription.current_period_end = subscription.current_period_end + timedelta(days=365)  # 1 year renewal
    subscription.status = "active"
    subscription.updated_at = datetime.now(timezone.utc)

    db.commit()

    audit_log(db, tenant_id, user_context.get("user_id"), "RENEW", "subscription", str(subscription.id),
              {"payment_method": payment_method})

    return {
        "subscription_id": str(subscription.id),
        "new_period_end": subscription.current_period_end.isoformat(),
        "renewed": True
    }