from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class CustomerUpsert(BaseModel):
    externalId: str
    email: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    role: str = "customer"
    password: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ProductUpsert(BaseModel):
    externalId: str
    name: str
    price: float | None = None
    barcode: str | None = None
    restricted: bool = False
    taxCode: str | None = None
    variants: list[dict] = []

class InventoryAdjust(BaseModel):
    productId: str
    quantityDifference: int | None = None
    quantity: int | None = None