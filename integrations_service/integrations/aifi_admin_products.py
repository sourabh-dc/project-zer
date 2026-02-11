"""
Proxy endpoints for AiFi Admin "products" API.
These routes call into `integrations_service.core.helpers.aifi_services` which wraps httpx calls.
"""
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Body, Query, Path, Request, Response
import httpx

from integrations_service.core.helpers import aifi_services as aifi
from integrations_service.core.helpers.aifi_services import AIFI_BASE_URL, PATH_PRODUCTS, _headers

router = APIRouter(prefix="/integrations/vendors/aifi/admin", tags=["integrations"])


@router.get("/products")
async def list_products(
    offset: int = Query(0, ge=0),
    count: int = Query(100, ge=1, le=1000),
    q: str = Query(None, description="Optional search/query string supported by AiFi"),
    raw: bool = Query(False, description="Return raw AiFi page response including pagination metadata when true"),
) -> Dict:
    """List products from AiFi Admin API (single page).

    Use `raw=true` to return the full AiFi response including pagination metadata.
    """
    page = await aifi.fetch_products_page(offset=offset, count=count, q=q)
    if raw:
        return page
    # normalize to list of products
    products = page.get("products") or page.get("data") or []
    return {"products": products, "pagination": page.get("pagination")}


@router.get("/products/{product_id}")
async def get_product(product_id: str = Path(..., description="AiFi product id or externalId")) -> Dict:
    """Fetch a single product by AiFi id using the dedicated admin endpoint first, fallback to scanning list.
    """
    try:
        # try the direct product detail endpoint
        detail = await aifi.fetch_product_detail(product_id)
        # remote may wrap the product in a `product` key
        if isinstance(detail, dict) and ("product" in detail) and isinstance(detail.get("product"), dict):
            return detail.get("product")
        return detail
    except Exception:
        # fallback to scanning the paged list (load first page with large count)
        products = await aifi.fetch_products()
        if isinstance(products, dict):
            products = products.get("products") or products.get("data") or []
        for p in products or []:
            if str(p.get("id")) == product_id or str(p.get("productId")) == product_id or str(p.get("externalId")) == product_id:
                return p
        raise HTTPException(status_code=404, detail="Product not found")


@router.post("/products")
async def create_product(payload: Dict = Body(..., description="AiFi product payload")) -> Dict:
    """Create a product in AiFi Admin API."""
    resp = await aifi.create_product(payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.put("/products/{product_id}")
async def update_product(product_id: str, payload: Dict = Body(...)) -> Dict:
    """Update a product in AiFi Admin API by AiFi product id."""
    resp = await aifi.update_product(product_id, payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.delete("/products/{product_id}")
async def delete_product(product_id: str) -> Dict:
    """Delete a product in AiFi Admin API by AiFi product id."""
    resp = await aifi.delete_product(product_id)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"status": resp.status_code, "body": resp.text}


@router.post("/products/bulk")
async def bulk_create_products(payloads: List[Dict] = Body(..., description="List of AiFi product payloads")) -> Dict:
    """Create multiple products in AiFi Admin API. Each payload should include externalId to help idempotency."""
    results = []
    for p in payloads:
        try:
            resp = await aifi.create_product(p)
            if resp.status_code >= 400:
                results.append({"externalId": p.get("externalId"), "status": "error", "code": resp.status_code, "body": resp.text})
            else:
                try:
                    results.append({"externalId": p.get("externalId"), "status": "ok", "body": resp.json()})
                except Exception:
                    results.append({"externalId": p.get("externalId"), "status": "ok", "body": resp.text})
        except Exception as exc:
            results.append({"externalId": p.get("externalId"), "status": "error", "error": str(exc)})
    return {"results": results}


@router.post("/products/upsert")
async def upsert_product_endpoint(payload: Dict = Body(..., description="AiFi product payload for upsert")) -> Dict:
    """Upsert a single product using AiFi Admin API. The helper will prefer updating if remote id is known.

    This endpoint calls the create endpoint with externalId param which AiFi accepts for idempotent upserts.
    """
    resp = await aifi.create_product(payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.api_route("/products/{subpath:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_product_subpath(subpath: str, request: Request):
    """Generic proxy for any AiFi admin product sub-endpoint not implemented above.

    This forwards the incoming request method, headers and body to the AiFi admin product endpoint
    at /api/admin/v2/products/{subpath} and returns the remote response.
    """
    url = f"{AIFI_BASE_URL}{PATH_PRODUCTS}/{subpath}"
    method = request.method
    params = dict(request.query_params)
    # read body (may be empty)
    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.request(method, url, headers=_headers(), params=params, content=body)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    content_type = resp.headers.get("content-type", "application/json")
    return Response(content=resp.content, status_code=resp.status_code, media_type=content_type)


# Also provide a catch-all for /products to forward methods other than GET/POST (if needed)
@router.api_route("/products", methods=["PUT", "PATCH", "DELETE"])
async def proxy_products_root(request: Request):
    url = f"{AIFI_BASE_URL}{PATH_PRODUCTS}"
    method = request.method
    params = dict(request.query_params)
    body = await request.body()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.request(method, url, headers=_headers(), params=params, content=body)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    content_type = resp.headers.get("content-type", "application/json")
    return Response(content=resp.content, status_code=resp.status_code, media_type=content_type)
