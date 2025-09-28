from fastapi import APIRouter, Body
from typing import List, Optional
from ..providers.aifi import AiFiProvider
from ..schemas.sync import CustomerUpsert, ProductUpsert, InventoryAdjust
from ..util.http import client
from ..config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
provider = AiFiProvider()

@router.get("/health")
def health(): return {"status": "ok"}

@router.get("/readiness")
def readiness(): return {"db": True, "redis": True}

@router.post("/ensure/customer")
async def ensure_customer(local_user_id: str = Body(..., embed=True), payload: Optional[CustomerUpsert] = None):
    body = payload.model_dump() if payload else {"externalId": local_user_id}
    out = await provider.ensure_customer(local_user_id=local_user_id, customer=body)
    return out

@router.post("/ensure/store")
async def ensure_store(local_store_id: str = Body(..., embed=True), store: dict | None = Body(None)):
    out = await provider.ensure_store(local_store_id=local_store_id, store=store)
    return out

@router.post("/sync/full")
async def sync_full(customers: List[CustomerUpsert] = Body(default=[]),
                    products: List[ProductUpsert] = Body(default=[]),
                    inventory: List[InventoryAdjust] = Body(default=[])):
    cust_results = []
    for c in customers:
        cust_results.append(await provider.push_customer(c.model_dump()))
    prod_results = []
    for p in products:
        prod_results.append(await provider.push_product(p.model_dump()))
    inv_results = []
    for a in inventory:
        inv_results.append(await provider.update_inventory(a.productId, quantity_difference=a.quantityDifference, quantity=a.quantity))
    return {"customers": cust_results, "products": prod_results, "inventory": inv_results}

@router.post("/sync/run")
async def sync_run(task: str = Body(...), payload: dict = Body(default={})):  # cron-friendly
    if task == "customers":
        items = payload.get("items", [])
        return {"results": [await provider.push_customer(it) for it in items]}
    if task == "products":
        items = payload.get("items", [])
        return {"results": [await provider.push_product(it) for it in items]}
    if task == "inventory":
        items = payload.get("items", [])
        out = []
        for it in items:
            out.append(await provider.update_inventory(it.get("productId"), quantity_difference=it.get("quantityDifference"), quantity=it.get("quantity")))
        return {"results": out}
    if task == "stores":
        items = payload.get("items", [])
        out = []
        for it in items:
            out.append(await provider.ensure_store(local_store_id=it.get("local_store_id"), store=it.get("store")))
        return {"results": out}
    return {"error": "unknown_task"}