# services/catalog/main.py - ZeroQue Catalog Service V2
# Production-ready catalog service with Celery, RabbitMQ, and saga patterns

import os
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
import structlog
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker
from fastapi.security import HTTPBearer
from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session

from core.config import get_settings
from services.catalog.services.catalog_services import create_product, get_products, get_product, \
    create_product_variant, create_category, create_bundle
from .models import *
from .schemas import *
from .repositories.db_handler import SessionLocal, engine, set_rls_context
from .utils.user_auth import get_user_context, check_permission
from .utils.cataog_logger import logger
from .utils.metrics import *
from .repositories.outbox_repository import store_outbox_event

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "catalog"
SERVICE_VERSION = "2.0.0"
DATABASE_URL = get_settings().DATABASE_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
REDIS_URL = get_settings().REDIS_URL
ALLOW_DEMO = get_settings().ALLOW_DEMO
SERVICE_PORT = get_settings().SERVICE_PORT
ENVIRONMENT = get_settings().ENVIRONMENT
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
JWT_EXPIRATION_HOURS = get_settings().JWT_EXPIRATION_HOURS

# Security scheme
security = HTTPBearer(auto_error=False)

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# External service URLs
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8007")
INVENTORY_BASE = os.getenv("INVENTORY_BASE", "http://localhost:8008")

# Logging configuration
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


# Prometheus metrics - clear registry to avoid duplicates
from prometheus_client import REGISTRY
try:
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()

except:
    pass



# Circuit breaker for external services
circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

def get_db_with_rls(uctx: Dict = Depends(get_user_context)):
    """Database dependency with RLS"""
    db = SessionLocal()
    try:
        # Skip RLS in demo mode to avoid transaction issues
        if not ALLOW_DEMO:
            set_rls_context(db, uctx["tenant_id"], uctx.get("user_id"))
        yield db
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting catalog service", version=SERVICE_VERSION)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down catalog service")
app = FastAPI(
    title="ZeroQue Catalog Service",
    description="Production-ready catalog service with Celery and RabbitMQ",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://yourdomain.com"],  # Restrict origins
    allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


# API ENDPOINTS

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/products")
async def create_product_route( req: ProductRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    return await create_product(req, db, uctx)

@app.get("/products")
async def list_products(
    tenant_id: str = Query(...), vendor_id: Optional[str] = Query(None), category_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_db_with_rls)
):
    """List products for a tenant"""
    return await get_products(tenant_id, vendor_id, category_id, limit, offset, db)

@app.get("/products/{product_id}")
async def get_product_route(product_id: str, db: Session = Depends(get_db_with_rls)):
    """Get product by ID"""
    return await get_product(product_id, db)

@app.post("/products/{product_id}/variants")
async def create_product_variant_route(
    product_id: str, req: ProductVariantRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)
):
    """Create a product variant using saga pattern"""
    return await create_product_variant(product_id, req, db, uctx)

@app.post("/categories")
async def create_category_route(req: CategoryRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)):
    """Create a new category using saga pattern"""
    return await create_category(req, db, uctx)

# Phase 3: Bundle Endpoints
@app.post("/bundles")
async def create_bundle_route(
    req: ProductBundleRequest, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)
):
    """Create a new product bundle/kit - Phase 3"""
    return await create_bundle(req, db, uctx)

@app.get("/bundles")
async def list_bundles(
    tenant_id: str = Query(...),
    bundle_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: SessionLocal = Depends(get_db_with_rls)
):
    """List bundles/kits - Phase 3"""
    try:
        query = db.query(ProductBundleV2).filter(
            ProductBundleV2.tenant_id == uuid.UUID(tenant_id),
            ProductBundleV2.is_active == True
        )

        if bundle_type:
            query = query.filter(ProductBundleV2.bundle_type == bundle_type)

        bundles = query.offset(offset).limit(limit).all()

        return {
            "bundles": [
                {
                    "bundle_id": str(bundle.bundle_id),
                    "name": bundle.name,
                    "bundle_sku": bundle.bundle_sku,
                    "bundle_type": bundle.bundle_type,
                    "base_price_minor": bundle.base_price_minor,
                    "currency": bundle.currency,
                    "created_at": bundle.created_at.isoformat()
                }
                for bundle in bundles
            ],
            "total": len(bundles),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Failed to list bundles: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bundles/{bundle_id}")
async def get_bundle(
    bundle_id: str,
    db: SessionLocal = Depends(get_db_with_rls)
):
    """Get bundle details with components - Phase 3"""
    try:
        bundle = db.query(ProductBundleV2).filter(
            ProductBundleV2.bundle_id == uuid.UUID(bundle_id)
        ).first()

        if not bundle:
            raise HTTPException(status_code=404, detail="Bundle not found")

        # Get components
        components = db.query(BundleComponentV2).filter(
            BundleComponentV2.bundle_id == uuid.UUID(bundle_id)
        ).order_by(BundleComponentV2.sort_order).all()

        return {
            "bundle_id": str(bundle.bundle_id),
            "name": bundle.name,
            "description": bundle.description,
            "bundle_sku": bundle.bundle_sku,
            "bundle_type": bundle.bundle_type,
            "base_price_minor": bundle.base_price_minor,
            "currency": bundle.currency,
            "is_active": bundle.is_active,
            "components": [
                {
                    "component_id": str(component.component_id),
                    "product_id": str(component.product_id),
                    "variant_id": str(component.variant_id) if component.variant_id else None,
                    "quantity": component.quantity,
                    "price_override_minor": component.price_override_minor,
                    "is_required": component.is_required,
                    "sort_order": component.sort_order
                }
                for component in components
            ],
            "created_at": bundle.created_at.isoformat(),
            "updated_at": bundle.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get bundle: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Phase 3: Barcode Sync Endpoint
@app.post("/products/{product_id}/barcode-sync")
async def sync_product_barcode(
    product_id: str,
    db: SessionLocal = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Sync product barcode to CV Connector - Phase 3"""
    try:
        # Check permissions
        if not check_permission("catalog.admin", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Get product
        product = db.query(ProductV2).filter(
            ProductV2.product_id == uuid.UUID(product_id)
        ).first()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        if not product.barcode:
            raise HTTPException(status_code=400, detail="Product has no barcode")

        # Publish barcode sync event
        event_data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "BARCODE_SYNC",
            "tenant_id": uctx["tenant_id"],
            "product_id": product_id,
            "barcode": product.barcode,
            "product_name": product.name,
            "sku": product.sku,
            "created_by": uctx["user_id"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Store event in outbox for CV Connector consumption
        store_outbox_event(db, event_data, "catalog_events")

        return {
            "product_id": product_id,
            "barcode": product.barcode,
            "sync_status": "queued",
            "message": "Barcode sync event published to CV Connector"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync barcode: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def search_products(
    req: ProductSearchRequest,
    db: SessionLocal = Depends(get_db_with_rls)
):
    """Search products"""
    try:
        query = "SELECT * FROM products_v2 WHERE 1=1"
        params = {"limit": req.limit, "offset": req.offset}
        
        if req.query:
            query += " AND (name ILIKE :query OR description ILIKE :query OR sku ILIKE :query)"
            params["query"] = f"%{req.query}%"
        
        if req.category_id:
            query += " AND category_id = :category_id"
            params["category_id"] = req.category_id
        
        if req.vendor_id:
            query += " AND vendor_id = :vendor_id"
            params["vendor_id"] = req.vendor_id
        
        if req.min_price:
            query += " AND base_price_minor >= :min_price"
            params["min_price"] = req.min_price
        
        if req.max_price:
            query += " AND base_price_minor <= :max_price"
            params["max_price"] = req.max_price
        
        query += " AND is_active = true ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        
        products = db.execute(text(query), params).fetchall()
        
        return [dict(product._mapping) for product in products]
        
    except Exception as e:
        logger.error("Product search failed", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8215")))
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )