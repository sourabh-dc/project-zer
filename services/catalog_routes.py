import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_
from uuid import UUID

from Models import (
    Tenant, Category, Product, Variant, StoreProduct, Store, Vendor
)
from Schemas import (
    CategoryRequest, ProductRequest, VariantRequest, StoreProductRequest,
    UserContext
)
from core.db_config import get_db
from core.permission_check_helpers import require_permission


router = APIRouter(prefix="/catalog", tags=["Catalog"])

# =============================================================================
# CATEGORY ENDPOINTS
# =============================================================================

@router.post("/categories", status_code=201)
async def create_category(
    req: CategoryRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.categories.manage"))
):
    if str(ctx.tenant_id) != req.tenant_id:
        raise HTTPException(403, "Tenant mismatch")

    # Enforce tenant-scoped unique code
    exists = db.query(Category).filter(
        Category.tenant_id == ctx.tenant_id,
        Category.code == req.code,
        Category.deleted_at.is_(None)
    ).first()
    if exists:
        raise HTTPException(409, "Category code already exists")

    parent_id = None
    if req.parent_category_id:
        try:
            parent_id = UUID(req.parent_category_id)
        except ValueError:
            raise HTTPException(400, "Invalid parent_category_id format")

        parent = db.query(Category).filter(
            Category.category_id == parent_id,
            Category.tenant_id == ctx.tenant_id,
            Category.deleted_at.is_(None)
        ).first()
        if not parent:
            raise HTTPException(404, "Parent category not found")

    category = Category(
        category_id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        name=req.name.strip(),
        code=req.code.strip(),
        description=req.description,
        parent_category_id=parent_id,
        active=True
    )
    db.add(category)
    try:
        db.commit()
        db.refresh(category)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Category code conflict")

    return {
        "category_id": str(category.category_id),
        "name": category.name,
        "code": category.code,
        "parent_category_id": str(parent_id) if parent_id else None,
        "active": True
    }


@router.get("/categories")
async def list_categories(
    active: Optional[bool] = Query(None),
    parent_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.categories.view"))
):
    q = db.query(Category).filter(
        Category.tenant_id == ctx.tenant_id,
        Category.deleted_at.is_(None)
    )

    if active is not None:
        q = q.filter(Category.active == active)
    if parent_id:
        q = q.filter(Category.parent_category_id == UUID(parent_id))

    total = q.count()
    items = q.order_by(Category.name).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "categories": [
            {
                "category_id": str(c.category_id),
                "name": c.name,
                "code": c.code,
                "parent_category_id": str(c.parent_category_id) if c.parent_category_id else None,
                "active": c.active,
                "has_children": db.query(Category).filter(
                    Category.parent_category_id == c.category_id,
                    Category.deleted_at.is_(None)
                ).count() > 0
            }
            for c in items
        ]
    }


# =============================================================================
# PRODUCT ENDPOINTS
# =============================================================================

@router.post("/products", status_code=201)
async def create_product(
    req: ProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.manage"))
):
    if str(ctx.tenant_id) != req.tenant_id:
        raise HTTPException(403, "Tenant mismatch")

    # SKU must be unique per tenant
    if db.query(Product).filter(
        Product.tenant_id == ctx.tenant_id,
        Product.sku == req.sku,
        Product.deleted_at.is_(None)
    ).first():
        raise HTTPException(409, "SKU already exists in your catalog")

    category_id = None
    if req.category_id:
        try:
            category_id = UUID(req.category_id)
        except ValueError:
            raise HTTPException(400, "Invalid category_id")
        if not db.query(Category).filter(
            Category.category_id == category_id,
            Category.tenant_id == ctx.tenant_id,
            Category.deleted_at.is_(None)
        ).first():
            raise HTTPException(404, "Category not found")

    vendor_id = None
    if req.vendor_id:
        try:
            vendor_id = UUID(req.vendor_id)
        except ValueError:
            raise HTTPException(400, "Invalid vendor_id")
        if not db.query(Vendor).filter(
            Vendor.vendor_id == vendor_id,
            Vendor.tenant_id == ctx.tenant_id
        ).first():
            raise HTTPException(404, "Vendor not found")

    product = Product(
        product_id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        vendor_id=vendor_id,
        category_id=category_id,
        sku=req.sku.strip(),
        name=req.name.strip(),
        description=req.description,
        brand=req.brand,
        base_price_minor=req.base_price_minor,
        currency=req.currency or "GBP",
        tax_rate=req.tax_rate or 0.0,
        product_type=req.product_type or "physical",
        product_metadata=req.product_metadata or {},
        active=True
    )
    db.add(product)
    try:
        db.commit()
        db.refresh(product)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(409, "SKU or data conflict")

    return {
        "product_id": str(product.product_id),
        "sku": product.sku,
        "name": product.name,
        "base_price_minor": product.base_price_minor,
        "active": True
    }


@router.get("/products")
async def list_products(
    category_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.products.view"))
):
    q = db.query(Product).filter(
        Product.tenant_id == ctx.tenant_id,
        Product.deleted_at.is_(None)
    )

    if category_id:
        q = q.filter(Product.category_id == UUID(category_id))
    if vendor_id:
        q = q.filter(Product.vendor_id == UUID(vendor_id))
    if active is not None:
        q = q.filter(Product.active == active)
    if search:
        q = q.filter(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.sku.ilike(f"%{search}%"),
                Product.brand.ilike(f"%{search}%")
            )
        )

    total = q.count()
    items = q.order_by(Product.name).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": [
            {
                "product_id": str(p.product_id),
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand,
                "base_price_minor": p.base_price_minor,
                "currency": p.currency,
                "category_id": str(p.category_id) if p.category_id else None,
                "active": p.active
            }
            for p in items
        ]
    }


# =============================================================================
# VARIANT ENDPOINTS
# =============================================================================

@router.post("/variants", status_code=201)
async def create_variant(
    req: VariantRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("catalog.variants.manage"))
):
    try:
        product_id = UUID(req.product_id)
    except ValueError:
        raise HTTPException(400, "Invalid product_id")

    product = db.query(Product).filter(
        Product.product_id == product_id,
        Product.tenant_id == ctx.tenant_id,
        Product.deleted_at.is_(None)
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    if db.query(Variant).filter(
        Variant.tenant_id == ctx.tenant_id,
        Variant.sku == req.sku,
        Variant.deleted_at.is_(None)
    ).first():
        raise HTTPException(409, "Variant SKU already exists")

    variant = Variant(
        variant_id=uuid.uuid4(),
        product_id=product.product_id,
        tenant_id=ctx.tenant_id,
        sku=req.sku.strip(),
        name=req.name.strip(),
        attributes=req.attributes or {},
        price_minor=req.price_minor or product.base_price_minor,
        currency=req.currency or "GBP",
        stock_quantity=req.stock_quantity or 0,
        active=True
    )
    db.add(variant)
    try:
        db.commit()
        return {"variant_id": str(variant.variant_id), "sku": variant.sku}
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Variant SKU conflict")


# =============================================================================
# STORE PRODUCT ENDPOINTS
# =============================================================================

@router.post("/v1/store-products", status_code=201)
async def add_product_to_store(
    req: StoreProductRequest,
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.products.manage"))
):
    try:
        store_id = UUID(req.store_id)
        product_id = UUID(req.product_id)
    except ValueError:
        raise HTTPException(400, "Invalid store_id or product_id")

    store = db.query(Store).filter(
        Store.store_id == store_id,
        Store.tenant_id == ctx.tenant_id
    ).first()
    if not store:
        raise HTTPException(404, "Store not found")

    product = db.query(Product).filter(
        Product.product_id == product_id,
        Product.tenant_id == ctx.tenant_id,
        Product.deleted_at.is_(None)
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    existing = db.query(StoreProduct).filter(
        StoreProduct.store_id == store_id,
        StoreProduct.product_id == product_id
    ).first()
    if existing:
        raise HTTPException(409, "Product already in store")

    sp = StoreProduct(
        id=uuid.uuid4(),
        store_id=store_id,
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        price_minor=req.price_minor or product.base_price_minor,
        currency=req.currency or "GBP",
        is_available=True,
        stock_quantity=req.stock_quantity or 0
    )
    db.add(sp)
    db.commit()

    return {
        "store_product_id": str(sp.id),
        "product_id": str(product_id),
        "store_id": str(store_id),
        "price_minor": sp.price_minor,
        "is_available": True
    }


@router.get("/v1/stores/{store_id}/products")
async def list_store_products(
    store_id: str,
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_permission("stores.products.view"))
):
    try:
        store_uuid = UUID(store_id)
    except ValueError:
        raise HTTPException(400, "Invalid store_id")

    store = db.query(Store).filter(
        Store.store_id == store_uuid,
        Store.tenant_id == ctx.tenant_id
    ).first()
    if not store:
        raise HTTPException(404, "Store not found")

    q = db.query(StoreProduct, Product, Variant).outerjoin(
        Product, StoreProduct.product_id == Product.product_id
    ).outerjoin(
        Variant, and_(Variant.product_id == Product.product_id, Variant.active == True)
    ).filter(
        StoreProduct.store_id == store_uuid,
        StoreProduct.tenant_id == ctx.tenant_id
    )

    total = q.count()
    results = q.offset(offset).limit(limit).all()

    products = []
    seen = set()
    for sp, p, v in results:
        key = str(p.product_id)
        if key in seen:
            continue
        seen.add(key)
        products.append({
            "product_id": str(p.product_id),
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand,
            "store_price_minor": sp.price_minor,
            "currency": sp.currency,
            "is_available": sp.is_available,
            "stock_quantity": sp.stock_quantity,
            "variants": []  # You can expand this later
        })

    return {
        "store_id": store_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "products": products
    }