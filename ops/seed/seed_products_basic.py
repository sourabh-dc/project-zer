from zeroque_common.db.session import get_engine, init_db, SessionLocal
from zeroque_common.models.products import Product, Price
CATALOG = [
    ("SKU-1","Gloves","Nitrile gloves", True, 1000),
    ("SKU-2","Mask","FFP2 mask", True, 1000),
    ("SKU-3","Bits","Drill bits set", True, 2000),
    ("SKU-4","More Bits","Premium drill bit", True, 5000),
]

def upsert(model, where: dict, values: dict, db):
    obj = db.query(model).filter_by(**where).one_or_none()
    if obj:
        for k,v in values.items():
            setattr(obj, k, v)
        db.commit(); return obj
    obj = model(**{**where, **values})
    db.add(obj); db.commit(); return obj

if __name__ == "__main__":
    get_engine(); init_db()
    with SessionLocal() as db:
        for sku, name, desc, active, unit_minor in CATALOG:
            upsert(Product, {"sku": sku}, {"name": name, "description": desc, "active": active}, db)
            upsert(Price, {"sku": sku, "currency": "GBP"}, {"unit_minor": unit_minor, "active": True}, db)
        print("Seed complete: products + prices")