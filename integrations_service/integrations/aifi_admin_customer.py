"""
APIs that proxy AiFi Admin "customers" endpoints.
These routes call into `integrations_service.core.helpers.aifi_services` which contains the
httpx client wrappers. Responses are returned as-is where possible and HTTP errors
from the remote service are translated into FastAPI HTTPExceptions.
"""
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Body, Query

from integrations_service.core.helpers import aifi_services as aifi

# Keep the same admin prefix used in other aiFi admin routes
router = APIRouter(prefix="/integrations/vendors/aifi/admin", tags=["integrations"])


@router.get("/customers")
async def list_customers():
    """Fetch customers from AiFi Admin API."""
    data = await aifi.fetch_customers()
    return data


@router.post("/customers")
async def create_customer(payload: Dict = Body(..., description="Customer payload for AiFi Admin API")):
    """Create a customer in AiFi Admin API.

    The payload should follow AiFi's customer shape (externalId, email, firstName, lastName, ...)
    """
    resp = await aifi.create_customer(payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.patch("/customers/{customer_id}")
async def patch_customer(customer_id: str, payload: Dict = Body(...)):
    """Patch (partial update) a customer in AiFi by AiFi customer id."""
    resp = await aifi.patch_customer(customer_id, payload)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str):
    """Delete a customer in AiFi by AiFi customer id (best-effort)."""
    resp = await aifi.delete_customer(customer_id)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"status": resp.status_code, "body": resp.text}


@router.post("/customers/{customer_id}/entry-codes")
async def generate_entry_code(customer_id: str, displayable: bool = Query(True)):
    """Generate an entry code for a customer. Returns the raw AiFi response body."""
    # aifi.generate_entry_code currently always sends displayable=true; keep param for future extension
    resp = await aifi.generate_entry_code(customer_id=customer_id)
    status = resp.get("status_code") if isinstance(resp, dict) else None
    body = resp.get("body") if isinstance(resp, dict) else None
    if status is None:
        raise HTTPException(status_code=500, detail="Invalid response from AiFi helper")
    if status >= 400:
        raise HTTPException(status_code=status, detail=body)
    try:
        import json

        return json.loads(body)
    except Exception:
        return {"status": status, "body": body}


@router.post("/entry-codes/verify")
async def verify_entry_code(code: str = Body(..., embed=True), store: Optional[str] = Body(None), location: Optional[str] = Body(None)):
    """Verify an entry code using AiFi API."""
    resp = await aifi.verify_entry_code(code=code, store=store, location=location)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.post("/customers/entered")
async def customer_entered(
    session_id: str = Body(...),
    role: str = Body("customer"),
    track_id: Optional[str] = Body(None),
    transaction_id: Optional[int] = Body(None),
    store: Optional[str] = Body(None),
    location: Optional[str] = Body(None),
):
    """Notify AiFi that a customer entered (helper for testing/webhooks)."""
    resp = await aifi.customer_entered(session_id=session_id, role=role, track_id=track_id, transaction_id=transaction_id, store=store, location=location)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.post("/customers/walked-out")
async def customer_walked_out(
    session_id: str = Body(...),
    role: str = Body("customer"),
    track_id: Optional[str] = Body(None),
    transaction_id: Optional[int] = Body(None),
    store: Optional[str] = Body(None),
    location: Optional[str] = Body(None),
):
    """Notify AiFi that a customer walked out."""
    resp = await aifi.customer_walked_out(session_id=session_id, role=role, track_id=track_id, transaction_id=transaction_id, store=store, location=location)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}


@router.post("/register-with-token")
async def register_with_token(
    token: str = Body(...),
    email: Optional[str] = Body(None),
    first_name: Optional[str] = Body(None),
    last_name: Optional[str] = Body(None),
    zone_id: Optional[int] = Body(None),
    scanner_id: Optional[int] = Body(None),
    token_type: str = Body("SESSION_ID"),
):
    """Register a customer with a token (AiFi helper)."""
    resp = await aifi.register_with_token(token=token, email=email, first_name=first_name, last_name=last_name, zone_id=zone_id, scanner_id=scanner_id, token_type=token_type)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text}
