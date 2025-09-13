from zeroque_common.db.session import get_engine, init_db, SessionLocal
from zeroque_common.models.usage import UsageMeter

METERS = [
    ("orders","Completed orders"),
    ("unique_shoppers","Unique shoppers"),
    ("api_calls","API call count"),
    ("webhook_volume","Webhooks received"),
    ("notifications_sent","Notifications sent"),
    ("storage_bytes","Storage used in bytes"),
    ("camera_count","Camera count"),
    ("uptime_minutes","Uptime in minutes"),
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
        for code, desc in METERS:
            upsert(UsageMeter, {"code": code}, {"description": desc}, db)
        print("Seed complete: usage meters")