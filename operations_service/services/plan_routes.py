from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from Models import SubscriptionPlan, PlanFeature, Feature, PlanPrice
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
            SubscriptionPlan.is_active == True
        ).all()

        if not plans:
            return {"plans": []}

        result = []
        for plan in plans:
            # Get all features for this plan
            plan_pricing = db.query(PlanPrice).filter(PlanPrice.plan_code == plan.code).first()
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
                "id": plan.plan_id,
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "currency": plan_pricing.currency,
                "pricing": {
                    "monthly": {
                        "amount_minor": plan_pricing.price_monthly_minor,
                        "amount": plan_pricing.price_monthly_minor  if plan_pricing.price_monthly_minor else None,
                        "available": True
                    },
                    "quarterly": {
                        "amount_minor": plan_pricing.price_quarterly_minor,
                        "amount": plan_pricing.price_quarterly_minor if plan_pricing.price_quarterly_minor else None,
                        "available": True
                    },
                    "yearly": {
                        "amount_minor": plan_pricing.price_yearly_minor,
                        "amount": plan_pricing.price_yearly_minor,
                        "available": True
                    }
                },
                "features": features_list,
                "active": plan.is_active,
                "created_at": plan.created_at.isoformat() if plan.created_at else None
            }

            result.append(plan_data)

        logger.info(f"Retrieved {len(result)} active plans")
        return {"plans": result}

    except Exception as e:
        logger.error(f"Failed to retrieve plans: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve plans")
