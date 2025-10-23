# =============================================================================
# PYDANTIC MODELS
# =============================================================================
from typing import Optional, Dict, List, Any

from pydantic import BaseModel


class OrderRequest(BaseModel):
    """Order creation request"""
    customer_id: str
    site_id: Optional[str] = None
    store_id: Optional[str] = None
    order_type: str = "purchase"
    items: List[Dict[str, Any]]
    shipping_address: Optional[Dict[str, Any]] = None
    billing_address: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

class OrderItemRequest(BaseModel):
    """Order item request"""
    product_id: str
    variant_id: Optional[str] = None
    quantity: int
    unit_price_minor: int

class OrderUpdateRequest(BaseModel):
    """Order update request"""
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
