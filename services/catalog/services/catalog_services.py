import time
import uuid
from typing import Dict

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from services.catalog.schemas import ProductRequest
from ..repositories.product_saga import ProductSaga
from ..utils.metrics import catalog_requests_total, catalog_request_duration
from ..utils.cataog_logger import logger


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