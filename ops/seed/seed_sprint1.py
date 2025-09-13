from zeroque_common.db.session import get_engine, init_db, SessionLocal
from zeroque_common.models.billing import Plan, Feature, PlanFeature

PLANS = [
    ("core","Core","Core plan"),
    ("pro","Pro","Pro plan"),
    ("enterprise","Enterprise","Enterprise plan"),
]

FEATURES = [
    ("multi_store","Multi-store support"),
    ("budgeting","Budgets & approvals"),
    ("analytics_basic","Basic analytics"),
    ("cv_aifi","AiFi CV driver"),
    ("api_rate_limit","API rate limits"),
]

PLAN_FEATURES = [
    ("core","multi_store", True, {"max_stores": 2}),
    ("core","budgeting", True, {"approvals": "basic"}),
    ("core","analytics_basic", True, {}),
    ("core","cv_aifi", True, {}),
    ("core","api_rate_limit", True, {"rpm": 60}),

    ("pro","multi_store", True, {"max_stores": 10}),
    ("pro","budgeting", True, {"approvals": "advanced"}),
    ("pro","analytics_basic", True, {"dashboards": "tenant"}),
    ("pro","cv_aifi", True, {}),
    ("pro","api_rate_limit", True, {"rpm": 300}),

    ("enterprise","multi_store", True, {"max_stores": 99999}),
    ("enterprise","budgeting", True, {"approvals": "advanced"}),
    ("enterprise","analytics_basic", True, {"dashboards": "tenant+site"}),
    ("enterprise","cv_aifi", True, {}),
    ("enterprise","api_rate_limit", True, {"rpm": 1000}),
]

def upsert(model, where: dict, values: dict, session):
    obj = session.query(model).filter_by(**where).one_or_none()
    if obj:
        for k,v in values.items():
            setattr(obj, k, v)
        session.commit()
        return obj
    obj = model(**{**where, **values})
    session.add(obj)
    session.commit()
    return obj

if __name__ == "__main__":
    get_engine(); init_db()
    with SessionLocal() as db:
        for code, name, desc in PLANS:
            upsert(Plan, {"code": code}, {"name": name, "description": desc}, db)

        for code, name in FEATURES:
            upsert(Feature, {"code": code}, {"name": name, "description": ""}, db)

        for plan_code, feature_code, enabled, limits in PLAN_FEATURES:
            upsert(PlanFeature, {"plan_code": plan_code, "feature_code": feature_code}, {"enabled": enabled, "limits": limits}, db)

        print("Seed complete: plans, features, plan_features")
