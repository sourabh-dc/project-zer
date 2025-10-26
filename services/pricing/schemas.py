from datetime import datetime
from typing import Optional, Dict, Any, List

from pydantic import BaseModel

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class PricebookRequest(BaseModel):
    """Pricebook creation request"""
    name: str
    description: Optional[str] = None
    currency: str = "GBP"
    metadata: Optional[Dict[str, Any]] = None

class PriceRuleRequest(BaseModel):
    """Price rule creation request"""
    pricebook_id: str
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    rule_type: str  # fixed, percentage, formula
    rule_value: float
    min_quantity: Optional[int] = None
    max_quantity: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

class PriceCalculationRequest(BaseModel):
    """Price calculation request"""
    product_id: str
    variant_id: Optional[str] = None
    pricebook_id: str
    quantity: int = 1
    base_price_minor: int

class PriceCalculationResponse(BaseModel):
    """Price calculation response"""
    product_id: str
    variant_id: Optional[str] = None
    pricebook_id: str
    quantity: int
    base_price_minor: int
    calculated_price_minor: int
    currency: str
    applied_rules: List[Dict[str, Any]] = []