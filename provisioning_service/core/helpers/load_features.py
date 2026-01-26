import csv
import uuid

from provisioning_service.Models import Feature, PlanFeature, SubscriptionPlan, PlanPrice
from provisioning_service.core.db_config import SessionLocal

'''Need to improve the logic'''
def insert_features_from_csv(csv_file: str):
    session = SessionLocal()
    try:
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing = session.query(Feature).filter_by(code=row["code"]).first()
                if not existing:
                    feature = Feature(
                        id=uuid.uuid4(),
                        code=row["code"],
                        name=row["name"],
                        description=row["description"] or "",
                        cluster=row["category"] or "general",
                        usage_type=row["usage_type"] or "count",
                        max_unit=row["max_unit"] or None,
                        reset_period=row["reset_period"] or "monthly",
                        active=True
                    )
                    session.add(feature)
                    plan=session.query(SubscriptionPlan).filter_by(code=row["plan"]).first()
                    if not plan:
                        plan=SubscriptionPlan(plan_id=uuid.uuid4(),code=row["plan"],name="Core Plan",description="The core plan",
                              created_by="zeroque_admin", is_active=True
                        )
                        session.add(plan)
                        session.flush()
                        pricing = PlanPrice(
                            plan_code=row["plan"],
                            price_monthly_minor=20,
                            currency="GBP",
                            quarterly_discount_pct=5,
                            yearly_discount_pct=10,
                            price_yearly_minor=57,
                            price_quarterly_minor=216
                        )
                        session.add(pricing)
                        session.flush()
                    plan_feature = PlanFeature(
                        plan_code=plan.code,
                        feature_code=feature.code,
                        enabled=True,
                        limits={}
                    )
                    session.add(plan_feature)
        session.commit()
        print("Features inserted successfully.")
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
    finally:
        session.close()
