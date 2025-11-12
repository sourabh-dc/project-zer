import uuid
from datetime import datetime
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from Models import Tenant, Category, Product, Variant
from Schemas import UserContext, CategoryRequest, ProductRequest, VariantRequest
from core.db_config import get_db
from core.permission_check_helpers import require_permission
from utils.logger import logger
from utils.metrics import req_total, req_duration

app = APIRouter()

# ==================================================================================
# CATALOG MANAGEMENT ENDPOINTS
# ==================================================================================

@app.post("/v1/catalog/categories", status_code=201)
async def create_category(
        req: CategoryRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.categories.manage",
                None
            )
        )
):
    """Create a new product category"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_category", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify parent category if provided
        parent_category_uuid = None
        if req.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == uuid.UUID(req.parent_category_id)).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent category not found")
            parent_category_uuid = uuid.UUID(req.parent_category_id)

        # Create category
        category = Category(
            category_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            name=req.name,
            code=req.code,
            description=req.description,
            parent_category_id=parent_category_uuid,
            active=True
        )
        db.add(category)
        db.commit()
        db.refresh(category)

        req_total.labels(operation="create_category", status="success").inc()
        req_duration.labels(operation="create_category").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created category: {category.category_id} ({category.name})")

        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "created_at": category.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or parent category ID format")
    except HTTPException:
        req_total.labels(operation="create_category", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        raise HTTPException(status_code=400, detail="Category code already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_category", status="error").inc()
        logger.error(f"❌ Category creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories")
async def list_categories(
        tenant_id: Optional[str] = Query(None),
        active: Optional[bool] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.categories.manage",
                None
            )
        )
):
    """List categories"""
    try:
        q = db.query(Category)
        if tenant_id:
            q = q.filter(Category.tenant_id == uuid.UUID(tenant_id))
        if active is not None:
            q = q.filter(Category.active == active)

        total = q.count()
        categories = q.order_by(Category.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "categories": [
                {
                    "category_id": str(c.category_id),
                    "tenant_id": str(c.tenant_id),
                    "name": c.name,
                    "code": c.code,
                    "description": c.description,
                    "parent_category_id": str(c.parent_category_id) if c.parent_category_id else None,
                    "active": c.active,
                    "created_at": c.created_at.isoformat()
                }
                for c in categories
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    except Exception as e:
        logger.error(f"❌ List categories failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/catalog/products", status_code=201)
async def create_product(
        req: ProductRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.manage",
                None
            )
        )
):
    """Create a new product"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_product", status="start").inc()

        # Verify tenant exists
        tenant = db.query(Tenant).filter(Tenant.tenant_id == uuid.UUID(req.tenant_id)).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Verify category if provided
        category_uuid = None
        if req.category_id:
            category = db.query(Category).filter(Category.category_id == uuid.UUID(req.category_id)).first()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")
            category_uuid = uuid.UUID(req.category_id)

        # Create product
        product = Product(
            product_id=uuid.uuid4(),
            tenant_id=uuid.UUID(req.tenant_id),
            category_id=category_uuid,
            sku=req.sku,
            name=req.name,
            description=req.description,
            brand=req.brand,
            manufacturer=req.manufacturer,
            base_price_minor=req.base_price_minor,
            currency=req.currency,
            tax_rate=req.tax_rate,
            product_type=req.product_type,
            active=True,
            product_metadata=req.product_metadata
        )
        db.add(product)
        db.commit()
        db.refresh(product)

        req_total.labels(operation="create_product", status="success").inc()
        req_duration.labels(operation="create_product").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created product: {product.product_id} ({product.name})")

        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "category_id": str(product.category_id) if product.category_id else None,
            "sku": product.sku,
            "name": product.name,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "created_at": product.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid tenant ID or category ID format")
    except HTTPException:
        req_total.labels(operation="create_product", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        raise HTTPException(status_code=400, detail="Product SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_product", status="error").inc()
        logger.error(f"❌ Product creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products")
async def list_products(
        tenant_id: Optional[str] = Query(None),
        category_id: Optional[str] = Query(None),
        active: Optional[bool] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.view",
                None
            )
        )
):
    """List products"""
    try:
        q = db.query(Product)
        if tenant_id:
            q = q.filter(Product.tenant_id == uuid.UUID(tenant_id))
        if category_id:
            q = q.filter(Product.category_id == uuid.UUID(category_id))
        if active is not None:
            q = q.filter(Product.active == active)

        total = q.count()
        products = q.order_by(Product.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "products": [
                {
                    "product_id": str(p.product_id),
                    "tenant_id": str(p.tenant_id),
                    "category_id": str(p.category_id) if p.category_id else None,
                    "sku": p.sku,
                    "name": p.name,
                    "description": p.description,
                    "brand": p.brand,
                    "base_price_minor": p.base_price_minor,
                    "currency": p.currency,
                    "active": p.active,
                    "created_at": p.created_at.isoformat()
                }
                for p in products
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except Exception as e:
        logger.error(f"❌ List products failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/v1/catalog/variants", status_code=201)
async def create_variant(
        req: VariantRequest,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.variants.manage",
                None
            )
        )
):
    """Create a new product variant"""
    start = datetime.now()
    try:
        req_total.labels(operation="create_variant", status="start").inc()

        # Verify product exists and get tenant_id
        product = db.query(Product).filter(Product.product_id == uuid.UUID(req.product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Create variant
        variant = Variant(
            variant_id=uuid.uuid4(),
            product_id=uuid.UUID(req.product_id),
            tenant_id=product.tenant_id,
            sku=req.sku,
            name=req.name,
            attributes=req.attributes,
            price_minor=req.price_minor,
            currency=req.currency,
            stock_quantity=req.stock_quantity,
            low_stock_threshold=req.low_stock_threshold,
            active=True
        )
        db.add(variant)
        db.commit()
        db.refresh(variant)

        req_total.labels(operation="create_variant", status="success").inc()
        req_duration.labels(operation="create_variant").observe(
            (datetime.now() - start).total_seconds()
        )

        logger.info(f"✅ Created variant: {variant.variant_id} ({variant.name})")

        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "created_at": variant.created_at.isoformat()
        }
    except ValueError:
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        req_total.labels(operation="create_variant", status="error").inc()
        raise
    except IntegrityError:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        raise HTTPException(status_code=400, detail="Variant SKU already exists")
    except Exception as e:
        db.rollback()
        req_total.labels(operation="create_variant", status="error").inc()
        logger.error(f"❌ Variant creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}")
async def get_product(
        product_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.view",
                None
            )
        )
):
    """Get a specific product by ID"""
    try:
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Get category details if exists
        category = None
        if product.category_id:
            category = db.query(Category).filter(Category.category_id == product.category_id).first()

        return {
            "product_id": str(product.product_id),
            "tenant_id": str(product.tenant_id),
            "category_id": str(product.category_id) if product.category_id else None,
            "category_name": category.name if category else None,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "brand": product.brand,
            "manufacturer": product.manufacturer,
            "base_price_minor": product.base_price_minor,
            "currency": product.currency,
            "tax_rate": product.tax_rate,
            "product_type": product.product_type,
            "active": product.active,
            "product_metadata": product.product_metadata,
            "created_at": product.created_at.isoformat(),
            "updated_at": product.updated_at.isoformat() if product.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/variants")
async def get_product_variants(
        product_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.view",
                None
            )
        )
):
    """Get all variants for a specific product"""
    try:
        # Verify product exists
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Get variants
        variants = db.query(Variant).filter(
            Variant.product_id == uuid.UUID(product_id)
        ).order_by(Variant.created_at.desc()).all()

        return {
            "product_id": product_id,
            "product_name": product.name,
            "product_sku": product.sku,
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": len(variants)
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/products/{product_id}/category")
async def get_product_category(
        product_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.view",
                None
            )
        )
):
    """Get category for a specific product"""
    try:
        # Get product
        product = db.query(Product).filter(Product.product_id == uuid.UUID(product_id)).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Get category
        if not product.category_id:
            return {
                "product_id": product_id,
                "product_name": product.name,
                "category": None,
                "message": "No category assigned to this product"
            }

        category = db.query(Category).filter(Category.category_id == product.category_id).first()

        return {
            "product_id": product_id,
            "product_name": product.name,
            "category": {
                "category_id": str(category.category_id),
                "name": category.name,
                "code": category.code,
                "description": category.description,
                "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
                "active": category.active
            } if category else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants")
async def list_variants(
        product_id: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        limit: int = Query(100, le=1000, ge=1),
        offset: int = Query(0, ge=0),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.view",
                None
            )
        )
):
    """List product variants"""
    try:
        q = db.query(Variant)
        if product_id:
            q = q.filter(Variant.product_id == uuid.UUID(product_id))

        total = q.count()
        variants = q.order_by(Variant.created_at.desc()).limit(limit).offset(offset).all()

        return {
            "variants": [
                {
                    "variant_id": str(v.variant_id),
                    "product_id": str(v.product_id),
                    "sku": v.sku,
                    "name": v.name,
                    "attributes": v.attributes,
                    "price_minor": v.price_minor,
                    "currency": v.currency,
                    "stock_quantity": v.stock_quantity,
                    "low_stock_threshold": v.low_stock_threshold,
                    "active": v.active,
                    "created_at": v.created_at.isoformat()
                }
                for v in variants
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    except Exception as e:
        logger.error(f"❌ List variants failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/variants/{variant_id}")
async def get_variant(
        variant_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.products.view",
                None
            )
        )
):
    """Get a specific variant by ID"""
    try:
        variant = db.query(Variant).filter(Variant.variant_id == uuid.UUID(variant_id)).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variant not found")

        # Get product details
        product = db.query(Product).filter(Product.product_id == variant.product_id).first()

        return {
            "variant_id": str(variant.variant_id),
            "product_id": str(variant.product_id),
            "product_name": product.name if product else None,
            "product_sku": product.sku if product else None,
            "tenant_id": str(variant.tenant_id),
            "sku": variant.sku,
            "name": variant.name,
            "attributes": variant.attributes,
            "price_minor": variant.price_minor,
            "currency": variant.currency,
            "stock_quantity": variant.stock_quantity,
            "low_stock_threshold": variant.low_stock_threshold,
            "active": variant.active,
            "created_at": variant.created_at.isoformat(),
            "updated_at": variant.updated_at.isoformat() if variant.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid variant ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get variant failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/v1/catalog/categories/{category_id}")
async def get_category(
        category_id: str,
        db: Session = Depends(get_db),
        ctx: UserContext = Depends(
            require_permission(
                "catalog.categories.manage",
                None
            )
        )
):
    """Get a specific category by ID"""
    try:
        category = db.query(Category).filter(Category.category_id == uuid.UUID(category_id)).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        # Get parent category if exists
        parent = None
        if category.parent_category_id:
            parent = db.query(Category).filter(Category.category_id == category.parent_category_id).first()

        # Get product count in this category
        product_count = db.query(Product).filter(Product.category_id == uuid.UUID(category_id)).count()

        return {
            "category_id": str(category.category_id),
            "tenant_id": str(category.tenant_id),
            "name": category.name,
            "code": category.code,
            "description": category.description,
            "parent_category_id": str(category.parent_category_id) if category.parent_category_id else None,
            "parent_category_name": parent.name if parent else None,
            "active": category.active,
            "product_count": product_count,
            "created_at": category.created_at.isoformat(),
            "updated_at": category.updated_at.isoformat() if category.updated_at else None
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get category failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")