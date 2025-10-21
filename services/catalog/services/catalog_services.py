import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from services.catalog.schemas import ProductRequest, ProductVariantRequest, CategoryRequest, ProductBundleRequest
from ..models import BundleComponentV2, ProductBundleV2
from ..repositories.catrgory_saga import CategorySaga
from ..repositories.database_ops import create_bundle_record, create_bundle_components
from ..repositories.outbox_repository import store_outbox_event
from ..repositories.product_saga import ProductSaga, fetch_products_from_db, get_product_by_id
from ..repositories.variant_saga import VariantSaga
from ..utils.metrics import catalog_requests_total, catalog_request_duration
from ..utils.cataog_logger import logger
from ..utils.user_auth import get_user_context, check_permission


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_external_service(url: str, method: str = "GET", data: Dict = None):
    """Call external service with retry"""
    with httpx.Client() as client:
        if method == "GET":
            response = client.get(url)
        elif method == "POST":
            response = client.post(url, json=data)
        elif method == "PUT":
            response = client.put(url, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")

        response.raise_for_status()
        return response.json()


async def create_product(req: ProductRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_product", status="start").inc()

        product_id = uuid.uuid4()
        tenant_id = uctx["tenant_id"]

        saga = ProductSaga(db)
        result = await saga.exec(product_id, tenant_id, req, uctx)

        catalog_requests_total.labels(endpoint="create_product", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_product").observe(time.time() - start)

        return result

    except ValueError as e:
        catalog_requests_total.labels(endpoint="create_product", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        catalog_requests_total.labels(endpoint="create_product", status="fail").inc()
        logger.error("Product creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_products(tenant_id: str, vendor_id: Optional[str], category_id: Optional[str], limit: int, offset: int,
                       db: Session):
    try:
        # Validate tenant_id is a valid UUID
        try:
            uuid.UUID(tenant_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid tenant_id format. Must be a valid UUID.")

        products = fetch_products_from_db(tenant_id=tenant_id, vendor_id=vendor_id, category_id=category_id, limit=limit,
            offset=offset, db=db)

        return products

    except Exception as e:
        logger.error("Failed to list products", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_product(product_id: str, db: Session):
    """Get product by ID"""
    try:
        product = get_product_by_id(db, product_id)
        return product
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get product", product_id=product_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


async def create_product_variant(product_id: str, req: ProductVariantRequest, db: Session, uctx: Dict):
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_variant", status="start").inc()
        variant_id = uuid.uuid4()
        saga = VariantSaga(db)
        res = await saga.exec(variant_id, product_id, req, uctx)
        catalog_requests_total.labels(endpoint="create_variant", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_variant").observe(time.time() - start)
        return res
    except ValueError as e:
        catalog_requests_total.labels(endpoint="create_variant", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        catalog_requests_total.labels(endpoint="create_variant", status="fail").inc()
        logger.error("Failed to create product variant", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def create_category(req: CategoryRequest, db: Session, uctx: Dict):
    """Create a new category using saga pattern"""
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_category", status="start").inc()
        category_id = uuid.uuid4()
        saga = CategorySaga(db)
        res = await saga.exec(category_id, uctx["tenant_id"], req, uctx)
        catalog_requests_total.labels(endpoint="create_category", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_category").observe(time.time() - start)
        return res
    except ValueError as e:
        catalog_requests_total.labels(endpoint="create_category", status="fail").inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        catalog_requests_total.labels(endpoint="create_category", status="fail").inc()
        logger.error("Failed to create category", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

async def create_bundle(req: ProductBundleRequest, db: Session, uctx: Dict):
    """Create a new product bundle/kit - Phase 3"""
    start = time.time()
    try:
        catalog_requests_total.labels(endpoint="create_bundle", status="start").inc()

        # Check permissions
        if not check_permission(uctx, "catalog.create"):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Create bundle
        bundle_id = uuid.uuid4()
        bundle = create_bundle_record(req, db, bundle_id, uctx)

        # Create bundle components
        create_bundle_components(req.components, db, bundle_id)

        # Publish PRODUCT_CREATED event for bundle
        event_data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "BUNDLE_CREATED",
            "tenant_id": uctx["tenant_id"],
            "bundle_id": str(bundle_id),
            "bundle_name": req.name,
            "bundle_sku": req.bundle_sku,
            "bundle_type": req.bundle_type,
            "component_count": len(req.components),
            "created_by": uctx["user_id"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Store event in outbox
        await store_outbox_event(db, "catalog_events", uctx["tenant_id"], bundle_id, event_data)

        catalog_requests_total.labels(endpoint="create_bundle", status="ok").inc()
        catalog_request_duration.labels(endpoint="create_bundle").observe(time.time() - start)

        return {
            "bundle_id": str(bundle_id),
            "bundle_name": req.name,
            "bundle_sku": req.bundle_sku,
            "bundle_type": req.bundle_type,
            "component_count": len(req.components),
            "created_at": bundle.created_at.isoformat()
        }

    except Exception as e:
        catalog_requests_total.labels(endpoint="create_bundle", status="fail").inc()
        logger.error(f"Failed to create bundle: {e}")
        raise HTTPException(status_code=500, detail=str(e))
