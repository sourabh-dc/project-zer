from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Models import SubscriptionPlan, PlanFeature, Feature
from core.db_config import get_db
from utils.logger import logger

router = APIRouter(prefix="/plans", tags=["Plan Management"])


@router.get("/", status_code=200)
async def get_plans(db: Session = Depends(get_db)):
    """
    Get all active subscription plans with their features and pricing.
    Returns both monthly and yearly prices for each plan.
    """
    try:
        plans = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.active == True
        ).all()

        if not plans:
            return {"plans": []}

        result = []
        for plan in plans:
            # Get all features for this plan
            plan_features = db.query(Feature, PlanFeature).join(
                PlanFeature, Feature.code == PlanFeature.feature_code
            ).filter(
                PlanFeature.plan_code == plan.code,
                PlanFeature.enabled == True,
                Feature.active == True
            ).all()

            # Format features
            features_list = []
            for feature, plan_feature in plan_features:
                features_list.append({
                    "code": feature.code,
                    "name": feature.name,
                    "description": feature.description,
                    "cluster": feature.cluster,
                    "usage_type": feature.usage_type,
                    "max_unit": feature.max_unit,
                    "reset_period": feature.reset_period,
                    "enabled": plan_feature.enabled
                })

            # Build plan response
            plan_data = {
                "id": plan.id,
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "currency": plan.currency,
                "pricing": {
                    "monthly": {
                        "amount_minor": plan.price_monthly_minor,
                        "amount": plan.price_monthly_minor / 100 if plan.price_monthly_minor else None,
                        "available": plan.price_monthly_minor is not None
                    },
                    "yearly": {
                        "amount_minor": plan.price_yearly_minor,
                        "amount": plan.price_yearly_minor / 100,
                        "available": True
                    }
                },
                "features": features_list,
                "active": plan.active,
                "created_at": plan.created_at.isoformat() if plan.created_at else None
            }

            result.append(plan_data)

        logger.info(f"Retrieved {len(result)} active plans")
        return {"plans": result}

    except Exception as e:
        logger.error(f"Failed to retrieve plans: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve plans")
