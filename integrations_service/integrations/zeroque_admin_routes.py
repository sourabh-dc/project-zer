from typing import List
from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session

from integrations_service.core.db_config import get_db
from integrations_service.Models import AifiStoreMap
from integrations_service.orders import upsert_aifi_order
from integrations_service.core.helpers import aifi_services as aifi
from integrations_service.Models import User, Product

router = APIRouter(prefix="/integrations/aifi/zeroque-admin", tags=["integrations"])


@router.get("/store-mappings")
async def list_store_mappings(db: Session = Depends(get_db)):
    rows = db.query(AifiStoreMap).all()
    return [
        {"aifi_store_id": r.aifi_store_id, "store_id": str(r.store_id)}
        for r in rows
    ]


@router.post("/store-mappings")
async def upsert_store_mapping(aifi_store_id: str, store_id: str, db: Session = Depends(get_db)):
    row = db.query(AifiStoreMap).filter(AifiStoreMap.aifi_store_id == aifi_store_id).first()
    if not row:
        row = AifiStoreMap(aifi_store_id=aifi_store_id, store_id=store_id)
    else:
        row.store_id = store_id
    db.add(row)
    db.commit()
    return {"aifi_store_id": aifi_store_id, "store_id": store_id}


@router.get("/reconcile/orders")
async def reconcile_orders(
    limit: int = Query(20, le=100),
    ingest: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Fetch recent AiFi orders, optionally ingest into our DB, and report unmapped customers/products.
    """
    remote = await aifi.fetch_orders(offset=0, count=limit)
    orders = remote.get("data") or remote.get("orders") or []

    unmapped_customers: List[str] = []
    unmapped_products: List[dict] = []
    ingested = []

    for o in orders:
        # Try to fetch detail to get products
        detail = o
        if "products" not in detail:
            try:
                detail = await aifi.fetch_order_detail(str(o.get("id")))
            except Exception:
                pass

        # Customer check
        aifi_cust = detail.get("customerId")
        if aifi_cust:
            user = db.query(User).filter(User.aifi_customer_id == str(aifi_cust)).first()
            if not user:
                unmapped_customers.append(str(aifi_cust))

        # Product checks
        for p in detail.get("products") or []:
            pid = p.get("productId") or p.get("id")
            barcode = p.get("barcode")
            sku = p.get("sku")
            prod = None
            if pid:
                prod = db.query(Product).filter(Product.aifi_product_id == str(pid)).first()
            if not prod and barcode:
                prod = db.query(Product).filter(Product.barcode == str(barcode)).first()
            if not prod and sku:
                prod = db.query(Product).filter(Product.sku == str(sku)).first()
            if not prod:
                unmapped_products.append({"productId": pid, "barcode": barcode, "sku": sku})

        if ingest:
            res = upsert_aifi_order(detail, db=db)
            ingested.append({"aifi_order_id": detail.get("id"), **res})

    return {
        "fetched": len(orders),
        "unmapped_customers": sorted(set(unmapped_customers)),
        "unmapped_products": unmapped_products,
        "ingested": ingested if ingest else [],
    }


@router.get("/reconcile/products")
async def reconcile_products(db: Session = Depends(get_db)):
    """List products missing AiFi mapping (no aifi_product_id)."""
    missing = db.query(Product).filter(Product.aifi_product_id == None).all()  # noqa: E711
    return [{"product_id": str(p.product_id), "sku": p.sku, "barcode": p.barcode, "name": p.name} for p in missing]


@router.get("/reconcile/customers")
async def reconcile_customers(db: Session = Depends(get_db)):
    """List users missing AiFi mapping (no aifi_customer_id)."""
    missing = db.query(User).filter(User.aifi_customer_id == None).all()  # noqa: E711
    return [{"user_id": str(u.user_id), "email": u.email, "name": f"{u.first_name} {u.last_name}"} for u in missing]

