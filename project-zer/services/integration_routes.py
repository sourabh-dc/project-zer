from fastapi import APIRouter

from core.helpers.aifi_services import generate_entry_code

app = APIRouter(prefix="/integration", tags=["Approvals"])

@app.post("/product-sync")
async def product_sync_with_cv():
    pass

@app.post("/customer-sync")
async def customer_sync_with_cv():
    pass

@app.post("/generate-qr")
async def generate_qr_code(customer_id: str):
    code  = await generate_entry_code(customer_id=customer_id)
    return dict(
        entry_code=code
    )

@app.post("/webhook")
async def webhook_handler():
    pass