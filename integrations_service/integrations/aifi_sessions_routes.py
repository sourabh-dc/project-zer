from fastapi import APIRouter, HTTPException

from integrations_service.core.helpers import aifi_services as aifi

router = APIRouter(prefix="/integrations/vendors/aifi", tags=["integrations"])


@router.get("/sessions")
async def list_sessions(offset: int = 0, count: int = 20, direction: str = "desc", order_by: str = "id"):
    return await aifi.list_sessions(offset=offset, count=count, direction=direction, order_by=order_by)


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, suspected_fraud: bool | None = None, metadata: dict | None = None):
    resp = await aifi.update_session(session_id, suspected_fraud=suspected_fraud, metadata=metadata)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


@router.post("/checkouts")
async def create_checkout(status: str, session_id: str, transaction_id: int, products: list[dict], store: str | None = None, location: str | None = None):
    resp = await aifi.create_checkout(status=status, session_id=session_id, transaction_id=transaction_id, products=products, store=store, location=location)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()
