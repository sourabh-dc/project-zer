from typing import Dict, List

from sqlalchemy.orm import Session

from integrations_service.Models import Product, StoreProduct
from integrations_service.core.db_config import SessionLocal
from integrations_service.core.helpers import aifi_services as aifi


def _store_prices_for_product(db: Session, product_id) -> List[Dict]:
    """Collect store-level prices for AiFi payload."""
    prices = []
    rows = (
        db.query(StoreProduct)
        .filter(StoreProduct.product_id == product_id)
        .all()
    )
    for row in rows:
        price_minor = row.price_minor or 0
        prices.append(
            {
                "storeId": str(row.store_id),
                "price": f"{price_minor/100:.2f}",
                "currency": row.currency,
            }
        )
    return prices


async def sync_products(delete_remote_missing: bool = False) -> Dict:
    """Reconcile and upsert products to AiFi. Optionally delete remote items missing locally."""
    remote_products = await aifi.fetch_products()
    existing_by_external = {
        str(p.get("externalId")): p for p in remote_products if p.get("externalId")
    }

    with SessionLocal() as db:
        products = db.query(Product).filter(Product.active == True).all()  # noqa: E712

        created = updated = skipped = 0
        results = []

        for product in products:
            if not product.barcode:
                skipped += 1
                results.append(
                    {"externalId": str(product.product_id), "status": "skip", "reason": "missing_barcode"}
                )
                continue

            store_prices = _store_prices_for_product(db, product.product_id)
            res = await aifi.upsert_product(product, existing_by_external, store_prices=store_prices)
            # persist remote id when created/updated
            if res.get("remote_id"):
                db.query(Product).filter(Product.product_id == product.product_id).update(
                    {"aifi_product_id": str(res["remote_id"])}
                )
                existing_by_external[str(product.product_id)] = {"id": res["remote_id"], "externalId": str(product.product_id)}
            results.append(res)
            status = res.get("status")
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1

        # Reconcile IDs from remote externalId mapping
        for ext, remote in existing_by_external.items():
            rid = remote.get("id") or remote.get("productId")
            if not rid:
                continue
            prod = db.query(Product).filter(Product.product_id == ext).first()
            if prod and not prod.aifi_product_id:
                prod.aifi_product_id = str(rid)
                db.add(prod)

        db.commit()

        local_ids = {str(p.product_id) for p in products}
        remote_ids = set(existing_by_external.keys())
        missing_on_remote = sorted(list(local_ids - remote_ids))
        missing_on_local = sorted(list(remote_ids - local_ids))

        deleted_remote = 0
        if delete_remote_missing and missing_on_local:
            for ext in missing_on_local:
                remote = existing_by_external.get(ext)
                if remote and remote.get("id"):
                    resp = await aifi.delete_product(str(remote["id"]))
                    if resp.status_code in (200, 204, 404):
                        deleted_remote += 1
                    results.append(
                        {
                            "externalId": ext,
                            "action": "delete_remote",
                            "status_code": resp.status_code,
                            "body": resp.text[:200],
                        }
                    )

        return {
            "total_local": len(products),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "missing_on_remote": missing_on_remote,
            "missing_on_local": missing_on_local,
            "deleted_remote": deleted_remote,
            "results": results,
        }

