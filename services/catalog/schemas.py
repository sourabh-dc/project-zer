from typing import Optional, Dict, Any, List

from pydantic import BaseModel


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class ProductRequest(BaseModel):
    """Product creation request - Phase 3 Enhanced"""
    vendor_id: str
    name: str
    description: Optional[str] = None
    sku: str
    barcode: Optional[str] = None  # Phase 3: Barcode for CV linkage
    category_id: Optional[str] = None
    brand: Optional[str] = None
    base_price_minor: int = 0
    currency: str = "GBP"
    weight_grams: Optional[int] = None
    dimensions_cm: Optional[Dict[str, float]] = None
    metadata: Optional[Dict[str, Any]] = None

class ProductVariantRequest(BaseModel):
    """Product variant creation request"""
    product_id: str
    name: str
    sku: str
    price_adjustment_minor: int = 0
    attributes: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None

class CategoryRequest(BaseModel):
    """Category creation request"""
    name: str
    description: Optional[str] = None
    parent_category_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

# Phase 3: Bundle Models
class BundleComponentRequest(BaseModel):
    """Bundle component request"""
    product_id: str
    variant_id: Optional[str] = None
    quantity: int = 1
    price_override_minor: Optional[int] = None
    is_required: bool = True
    sort_order: int = 0

class ProductBundleRequest(BaseModel):
    """Product bundle creation request - Phase 3"""
    name: str
    description: Optional[str] = None
    bundle_sku: str
    bundle_type: str = "bundle"  # "kit", "bundle", "package"
    base_price_minor: int = 0
    currency: str = "GBP"
    components: List[BundleComponentRequest]
    metadata: Optional[Dict[str, Any]] = None

class ProductSearchRequest(BaseModel):
    """Product search request"""
    query: Optional[str] = None
    category_id: Optional[str] = None
    vendor_id: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    limit: int = 50
    offset: int = 0