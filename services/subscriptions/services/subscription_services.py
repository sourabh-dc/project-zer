from typing import Dict, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.subscriptions.repositories.database_ops import create_feature_db, create_plan_db, add_feature_to_plan_db, \
    remove_feature_from_plan_db, renew_subscription_db
from services.subscriptions.schemas import CreatePlanRequest
from services.subscriptions.utils.user_auth import check_permission


async def create_feature(feature_data: Dict, user_context: Dict, db: Session):
    """Create a new feature"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
       return create_feature_db(feature_data, db)

    except IntegrityError:
        raise HTTPException(status_code=400, detail="Feature code already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def create_plan(req: CreatePlanRequest, user_context: Dict, db: Session
):
    """Create a new subscription plan"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        return create_plan_db(req, db)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Plan code already exists")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def add_feature_to_plan(plan_code: str, feature_code: str, limits: Optional[Dict], user_context: Dict, db):
    """Add a feature to a plan with optional limits"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        return  add_feature_to_plan_db(plan_code, feature_code, limits, db, user_context)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def remove_feature_from_plan(plan_code: str, feature_code: str, user_context: Dict, db:Session):
    """Remove a feature from a plan"""
    if not check_permission(user_context, "subscriptions.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        return remove_feature_from_plan_db(plan_code, feature_code, db, user_context)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def renew_subscription(tenant_id: str, payment_method: str, user_context: Dict, db: Session):
    """Renew a subscription"""
    if not check_permission(user_context, "subscriptions.renew"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        return renew_subscription_db(tenant_id, payment_method, db, user_context)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))