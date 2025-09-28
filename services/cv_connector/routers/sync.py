from fastapi import APIRouter
from typing import List
from ..providers.aifi import AiFiProvider
from ..schemas.sync import CustomerUpsert, ProductUpsert, InventoryAdjust

router = APIRouter(prefix="/sync", tags=["sync"])
provider = AiFiProvider()

@router.post("/customers:batch")
async def sync_customers(customers: List[CustomerUpsert]):
    out = []
    for c in customers:
        out.append(await provider.push_customer(c.model_dump()))
    return {"results": out}

@router.post("/products:batch")
async def sync_products(products: List[ProductUpsert]):
    out = []
    for p in products:
        out.append(await provider.push_product(p.model_dump()))
    return {"results": out}

@router.post("/inventory:batch")
async def sync_inventory(adjustments: List[InventoryAdjust]):
    out = []
    for a in adjustments:
        out.append(await provider.update_inventory(a.productId, quantity_difference=a.quantityDifference, quantity=a.quantity))
    return {"results": out}