from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from Models import Product, User
from core.db_config import get_db
from core.helpers import aifi_services as aifi

router = APIRouter(prefix="/integrations/vendors", tags=["integrations"])

SUPPORTED_VENDORS = {"aifi"}


def _ensure_vendor(vendor: str):
    if vendor not in SUPPORTED_VENDORS:
        raise HTTPException(status_code=400, detail=f"Unsupported vendor '{vendor}'")
    if vendor == "aifi":
        if not aifi.AIFI_API_KEY or not aifi.AIFI_BASE_URL:
            raise HTTPException(status_code=400, detail="AiFi credentials are not configured")


@router.get("/{vendor}/ping")
async def ping(vendor: str = Path(..., description="vendor key, e.g. 'aifi'")):
    """Connectivity check against the vendor adapter."""
    _ensure_vendor(vendor)
    ok, message = await aifi.test_aifi_connection()
    if not ok:
        raise HTTPException(status_code=502, detail=f"AiFi connectivity failed: {message}")
    return {"status": "ok", "message": message}


@router.get("/{vendor}/orders")
async def list_orders(vendor: str = Path(..., description="vendor key"), offset: int = 0, count: int = 20, status: str | None = None):
    """Fetch orders from AiFi Admin API to aid reconciliation/webhook testing."""
    _ensure_vendor(vendor)
    return await aifi.fetch_orders(offset=offset, count=count, status=status)


@router.post("/{vendor}/sync/products")
async def sync_products(vendor: str = Path(..., description="vendor key"), db: Session = Depends(get_db)):
    """Push local products to vendor (currently AiFi) create/update by externalId."""
    _ensure_vendor(vendor)
    remote_products = await aifi.fetch_products()
    existing_by_external = {
        str(p.get("externalId")): p for p in remote_products if p.get("externalId")
    }

    created = updated = skipped = 0
    results = []
    products = db.query(Product).filter(Product.active == True).all()  # noqa: E712

    for product in products:
        if not product.barcode:
            skipped += 1
            results.append({"externalId": str(product.product_id), "status": "skip", "reason": "missing_barcode"})
            continue
        res = await aifi.upsert_product(product, existing_by_external)
        results.append(res)
        status = res.get("status")
        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1
        else:
            skipped += 1

    return {
        "vendor": vendor,
        "total_local": len(products),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "results": results,
    }


@router.post("/{vendor}/sync/users")
async def sync_users(vendor: str = Path(..., description="vendor key"), db: Session = Depends(get_db)):
    """Push local users to vendor customers (create or update by externalId)."""
    _ensure_vendor(vendor)
    remote_customers = await aifi.fetch_customers()
    existing_by_external = {
        str(c.get("externalId")): c for c in remote_customers if c.get("externalId")
    }

    created = updated = skipped = 0
    results = []
    users = db.query(User).filter(User.active == True).all()  # noqa: E712

    for user in users:
        if not user.email:
            skipped += 1
            results.append({"externalId": str(user.user_id), "status": "skip", "reason": "missing_email"})
            continue
        res = await aifi.upsert_customer(user, existing_by_external)
        results.append(res)
        status = res.get("status")
        if status == "created":
            created += 1
        elif status == "updated":
            updated += 1
        else:
            skipped += 1

    return {
        "vendor": vendor,
        "total_local": len(users),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "results": results,
    }

