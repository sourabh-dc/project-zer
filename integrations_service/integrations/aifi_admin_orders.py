"""
Proxy endpoints for AiFi Admin "orders" API.
These routes call into `integrations_service.core.helpers.aifi_services` when helpers exist,
and proxy other calls to the AiFi Admin Orders endpoints.
"""
from typing import Dict

from fastapi import APIRouter, HTTPException, Body, Query, Path, Request, Response
import httpx

from integrations_service.core.helpers import aifi_services as aifi
from integrations_service.core.helpers.aifi_services import AIFI_BASE_URL, PATH_ORDERS, _headers

router = APIRouter(prefix="/integrations/vendors/aifi/admin", tags=["integrations"])


@router.get("/orders")
async def list_orders(offset: int = Query(0, ge=0), count: int = Query(20, ge=1, le=1000), status: str | None = Query(None)) -> Dict:
    """List orders from AiFi Admin API. Uses helper `fetch_orders` which returns parsed JSON."""
    try:
        return await aifi.fetch_orders(offset=offset, count=count, status=status)
    except httpx.HTTPStatusError as exc:
        # translate remote HTTP errors
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/orders/{order_id}")
async def get_order(order_id: str = Path(..., description="AiFi order id")) -> Dict:
    """Fetch a single order detail from AiFi Admin API using helper `fetch_order_detail`."""
    try:
        return await aifi.fetch_order_detail(order_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/orders")
async def create_order(payload: Dict = Body(...)) -> Dict:
    """Create a new order in AiFi Admin API (proxied)."""
    url = f"{AIFI_BASE_URL}{PATH_ORDERS}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=_headers(), json=payload)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.patch("/orders/{order_id}")
async def patch_order(order_id: str, payload: Dict = Body(...)) -> Dict:
    """Patch (partial update) an order in AiFi Admin API by order id (proxied)."""
    url = f"{AIFI_BASE_URL}{PATH_ORDERS}/{order_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.patch(url, headers=_headers(), json=payload)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.post("/orders/{order_id}/retry")
async def retry_order(order_id: str = Path(..., description="AiFi order id")) -> Dict:
    """Retry checkout for an order that failed (proxied)."""
    url = f"{AIFI_BASE_URL}{PATH_ORDERS}/{order_id}/retry"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=_headers())
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}
