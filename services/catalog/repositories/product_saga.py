import time
from typing import Optional, List

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.catalog.models import ProductV2
from services.catalog.repositories.outbox_repository import store_outbox_event
from ..utils.metrics import saga_total, saga_duration
from ..utils.cataog_logger import logger
from ..tasks.celery_tasks import publish_outbox_events
from .audit_repository import audit



class ProductSaga:
    """Saga for product creation with compensation"""

    def __init__(self, db):
        self.db = db
        self.product = None
        self.eid = None

    async def exec(self, product_id, tenant_id, req, uctx):
        """Execute product creation saga"""
        start = time.time()
        try:
            # Create product
            self.product = ProductV2(
                product_id=product_id,
                tenant_id=tenant_id,
                vendor_id=req.vendor_id,
                name=req.name,
                description=req.description,
                sku=req.sku,
                category_id=req.category_id,
                brand=req.brand,
                base_price_minor=req.base_price_minor,
                currency=req.currency,
                weight_grams=req.weight_grams,
                dimensions_cm=req.dimensions_cm
            )
            self.db.add(self.product)
            self.db.commit()
            self.db.refresh(self.product)

            # Store outbox event
            self.eid = store_outbox_event(self.db, "PRODUCT_CREATED", str(tenant_id), str(product_id), {
                "product_id": str(product_id),
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id
            })

            # Publish event
            publish_outbox_events.delay()

            # Audit log
            audit(self.db, str(tenant_id), uctx["user_id"], "CREATE", "product", str(product_id), {
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id
            })

            saga_total.labels(type="product", status="ok").inc()
            saga_duration.labels(type="product").observe(time.time() - start)

            return {
                "product_id": str(product_id),
                "name": req.name,
                "sku": req.sku,
                "vendor_id": req.vendor_id,
                "created": True
            }

        except Exception as e:
            await self.comp()
            saga_total.labels(type="product", status="fail").inc()
            raise

    async def comp(self):
        """Compensation logic"""
        try:
            if self.eid:
                self.db.execute(text("DELETE FROM outbox_events WHERE event_id = :id"), {"id": self.eid})
                self.db.commit()

            if self.product:
                self.db.delete(self.product)
                self.db.commit()

        except Exception as e:
            logger.error("Compensation failed", error=str(e))
            self.db.rollback()

def fetch_products_from_db(
    tenant_id: str,
    vendor_id: Optional[str],
    category_id: Optional[str],
    limit: int,
    offset: int,
    db: Session
) -> List[dict]:
    query = "SELECT * FROM products_v2 WHERE tenant_id = :tenant_id"
    params = {"tenant_id": tenant_id, "limit": limit, "offset": offset}

    if vendor_id:
        query += " AND vendor_id = :vendor_id"
        params["vendor_id"] = vendor_id

    if category_id:
        query += " AND category_id = :category_id"
        params["category_id"] = category_id

    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"

    result = db.execute(text(query), params).fetchall()
    return [dict(row._mapping) for row in result]

def get_product_by_id(db: Session, product_id: str) -> Optional[dict]:
    product = db.execute(
        text("SELECT * FROM products_v2 WHERE product_id = :id"),
        {"id": product_id}
    ).fetchone()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return dict(product._mapping)
