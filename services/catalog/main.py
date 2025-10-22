# services/catalog/main.py - ZeroQue Catalog Service V2
# Production-ready catalog service with Celery, RabbitMQ, and saga patterns

import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker
from fastapi.security import HTTPBearer
from fastapi import Depends
from sqlalchemy.orm import Session

from core.config import get_settings
from services.catalog.services.catalog_services import create_product, get_products, get_product, \
    create_product_variant, create_category, create_bundle, get_bundles, get_bundle, sync_product_barcode, \
    search_products
from .models import *
from .schemas import *
from .repositories.db_handler import SessionLocal, engine, set_rls_context
from .utils.user_auth import get_user_context
from .utils.cataog_logger import logger


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
async def list_bundles(tenant_id: str = Query(...), bundle_type: Optional[str] = Query(None), limit: int = Query(100, le=1000),
                       offset: int = Query(0, ge=0), db: Session = Depends(get_db_with_rls)
):
    """List bundles/kits - Phase 3"""
    return await get_bundles(db, tenant_id, bundle_type, limit, offset)

@app.get("/bundles/{bundle_id}")
async def get_bundle_route(
    bundle_id: str,
    db: Session = Depends(get_db_with_rls)
):
    """Get bundle details with components - Phase 3"""
    return await get_bundle(db, bundle_id)

# Phase 3: Barcode Sync Endpoint
@app.post("/products/{product_id}/barcode-sync")
async def sync_product_barcode_route(product_id: str, db: Session = Depends(get_db_with_rls), uctx: Dict = Depends(get_user_context)
):
    """Sync product barcode to CV Connector - Phase 3"""
    return sync_product_barcode(product_id, db, uctx)

@app.post("/search")
async def search_products_route(
    req: ProductSearchRequest,
    db: Session = Depends(get_db_with_rls)
):
    """Search products"""
    return search_products(req, db)

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