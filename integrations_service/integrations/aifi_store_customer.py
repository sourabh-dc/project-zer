from fastapi import APIRouter, HTTPException

from integrations_service.core.helpers import aifi_services as aifi

router = APIRouter(prefix="/integrations/aifi", tags=["integrations"])


@router.post("/customers/entered")
async def customer_entered(session_id: str, role: str = "customer", track_id: str | None = None, transaction_id: int | None = None, store: str | None = None, location: str | None = None):
    resp = await aifi.customer_entered(session_id=session_id, role=role, track_id=track_id, transaction_id=transaction_id, store=store, location=location)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.post("/customers/walked-out")
async def customer_walked_out(session_id: str, role: str = "customer", track_id: str | None = None, transaction_id: int | None = None, store: str | None = None, location: str | None = None):
    resp = await aifi.customer_walked_out(session_id=session_id, role=role, track_id=track_id, transaction_id=transaction_id, store=store, location=location)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@router.post("/customers/register-with-token")
async def register_with_token(token: str, email: str | None = None, first_name: str | None = None, last_name: str | None = None, zone_id: int | None = None, scanner_id: int | None = None, token_type: str = "SESSION_ID"):
    resp = await aifi.register_with_token(token=token, email=email, first_name=first_name, last_name=last_name, zone_id=zone_id, scanner_id=scanner_id, token_type=token_type)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "body": resp.text}