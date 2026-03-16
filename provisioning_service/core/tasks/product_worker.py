"""
product_worker.py
-----------------
Handles async post-processing for product-related outbox events:

- ``product.created``       – sync single product to AiFi CV
- ``product.bulk_created``  – sync a batch of products to AiFi CV
"""

import uuid
from typing import List
from sqlalchemy.orm import Session

from provisioning_service.Models import OutboxEvent, Product
from provisioning_service.core.helpers.aifi_services import cv_create_product
from provisioning_service.utils.logger import logger


async def handle_product_created(db: Session, payload_id: str) -> None:
    """
    Sync a single newly-created product to AiFi.

    event_data expected keys:
        product_id   – UUID string of the Product row
        tenant_id    – UUID string (for logging)
    """
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.payload or {}
    product_id = payload.get("product_id")
    if not product_id:
        raise ValueError("product_id missing in outbox payload")

    product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
    if not product:
        raise ValueError(f"Product {product_id} not found")

    logger.info(f"Product worker: syncing product {product_id} to AiFi")

    try:
        result = await cv_create_product({
            "externalId": str(product.product_id),
            "name": product.display_name,
            "barcode": product.ean or product.sku,
            "price": product.purchase_price_minor,
            "weight": str(product.weight) if product.weight else "0",
            "thumbnail": "",
        })
        product.aifi_product_id = result.get("id") if isinstance(result, dict) else None
        db.commit()
        logger.info(f"Product worker: AiFi sync succeeded for product {product_id}")
    except Exception as exc:
        db.rollback()
        logger.error(f"Product worker: AiFi sync failed for product {product_id}: {exc}")
        raise


async def handle_bulk_products_created(db: Session, payload_id: str) -> None:
    """
    Sync a batch of newly-created products to AiFi.

    event_data expected keys:
        product_ids  – list of UUID strings
        tenant_id    – UUID string (for logging)
    """
    outbox = db.query(OutboxEvent).filter(OutboxEvent.id == uuid.UUID(payload_id)).first()
    if not outbox:
        raise ValueError(f"Outbox event {payload_id} not found")

    payload = outbox.event_data or {}
    product_ids: List[str] = payload.get("product_ids", [])
    if not product_ids:
        logger.warning(f"Bulk product worker: no product_ids in outbox {payload_id}")
        return

    tenant_id = payload.get("tenant_id")
    logger.info(
        f"Bulk product worker: syncing {len(product_ids)} products "
        f"for tenant {tenant_id} (outbox {payload_id})"
    )

    failures = []
    for pid in product_ids:
        try:
            product = db.query(Product).filter(Product.product_id == uuid.UUID(pid)).first()
            if not product:
                logger.warning(f"Bulk product worker: product {pid} not found – skipping")
                continue

            result = await cv_create_product({
                "externalId": str(product.product_id),
                "name": product.display_name,
                "barcode": product.ean or product.sku,
                "price": product.purchase_price_minor,
                "weight": str(product.weight) if product.weight else "0",
                "thumbnail": "",
            })
            product.aifi_product_id = result.get("id") if isinstance(result, dict) else None
            db.commit()
            logger.info(f"Bulk product worker: AiFi sync succeeded for product {pid}")
        except Exception as exc:
            db.rollback()
            logger.error(f"Bulk product worker: AiFi sync failed for product {pid}: {exc}")
            failures.append(pid)

    if failures:
        raise RuntimeError(
            f"AiFi sync failed for {len(failures)}/{len(product_ids)} products: {failures}"
        )

