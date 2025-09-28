from fastapi import APIRouter, Body, HTTPException, Request
from ..providers.aifi import AiFiProvider
from ..schemas.webhooks import EntryWebhookDecision, SimpleOK
from ..services.orders import post_checkout_to_cv_gateway
from ..util.security import verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
provider = AiFiProvider()

@router.post("/entry-codes/validate", response_model=EntryWebhookDecision)
async def entry_codes_validate(request: Request, payload: dict = Body(...)):
    verify_webhook_signature(request, payload)
    decision = provider.adapt_entry_webhook_to_decision(payload)
    return decision

@router.post("/checkout", response_model=SimpleOK)
async def checkout(request: Request, payload: dict = Body(...)):
    verify_webhook_signature(request, payload)
    try:
        mapped = provider.adapt_checkout_to_order(payload)
        await post_checkout_to_cv_gateway(mapped)
        # Optional: return {"paymentTransactionIds": ["..."]} if you're the payment processor
        return SimpleOK(ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"order_ingest_failed: {e}")

# Optional observability webhooks
@router.post("/checkout_zone/entered")
async def checkout_zone_entered(_: dict = Body(...)): return "OK"

@router.post("/checkout_zone/left")
async def checkout_zone_left(_: dict = Body(...)): return "OK"

@router.post("/transitions/entered")
async def transitions_entered(_: dict = Body(...)): return "OK"

@router.post("/transitions/left")
async def transitions_left(_: dict = Body(...)): return "OK"