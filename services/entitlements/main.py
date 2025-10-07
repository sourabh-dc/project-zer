# services/entitlements/main.py - Production Ready Version
# Entitlements Service V2 - Pure Access Control & Usage Tracking
from fastapi import FastAPI, Body, Query, HTTPException, Path, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy import text, Column, String, Boolean, DateTime, Integer, BigInteger, JSON, func, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
import logging, os, json, uuid, httpx, redis
from datetime import datetime, timedelta
import asyncio
from contextlib import asynccontextmanager
import time
import prometheus_client
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Production Metrics
ENTITLEMENT_CHECKS = Counter('entitlement_checks_total', 'Total entitlement checks', ['tenant_id', 'feature_code', 'result'])
ENTITLEMENT_CHECK_DURATION = Histogram('entitlement_check_duration_seconds', 'Time spent checking entitlements')
USAGE_RECORDINGS = Counter('usage_recordings_total', 'Total usage recordings', ['tenant_id', 'feature_code'])
ACTIVE_CONNECTIONS = Gauge('active_connections', 'Active database connections')
CACHE_HITS = Counter('cache_hits_total', 'Cache hits', ['cache_type'])
CACHE_MISSES = Counter('cache_misses_total', 'Cache misses', ['cache_type'])

# Redis Cache Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = None

# Try to import common modules (fallback to basic implementations)
try:
    from zeroque_common.db.session import get_engine, init_db, check_db, SessionLocal
    from zeroque_common.observability import add_observability_middleware, add_api_call_meter
    from zeroque_common.health import HealthMonitor
    from zeroque_common.events import EventStreamManager
    from zeroque_common.metrics import metrics
    COMMON_MODULES_AVAILABLE = True
except ImportError:
    # Fallback implementations
    from sqlalchemy import create_engine
    
    def get_engine():
        return create_engine(os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5000/zeroque_dev"))
    
    def init_db():
        pass
    
    def check_db():
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except:
            return False
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    
    def add_observability_middleware(app, service_name):
        pass
    
    def add_api_call_meter(app):
        pass
    
    class HealthMonitor:
        def __init__(self, service_name):
            self.service_name = service_name
        
        async def check_system_health(self):
            return {"status": "ok", "service": self.service_name}
    
    class EventStreamManager:
        def emit_event(self, service_name, event_type, data):
            log.info(f"Event: {event_type} from {service_name}")
    
    class metrics:
        @staticmethod
        def counter(name):
            return type('Counter', (), {'inc': lambda: None})()
        
        @staticmethod
        def histogram(name):
            return type('Histogram', (), {'observe': lambda x: None})()
    
    COMMON_MODULES_AVAILABLE = False

# Fallback model definitions for usage tracking
Base = declarative_base()

class SubscriptionUsage(Base):
    __tablename__ = "subscription_usage"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(100), index=True)
    feature_code = Column(String(50), index=True)
    usage_type = Column(String(50), index=True)
    usage_count = Column(Integer, default=0)
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True))

# Lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    log.info("Starting Entitlements Service V2")
    init_db()
    
    # Create tables if they don't exist
    try:
        engine = get_engine()
        Base.metadata.create_all(bind=engine)
        log.info("Database tables created/verified")
    except Exception as e:
        log.error(f"Failed to create database tables: {str(e)}")
    
    # Initialize Redis connection
    global redis_client
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()  # Test connection
        log.info("Redis connection established")
    except Exception as e:
        log.warning(f"Redis connection failed: {str(e)}")
        redis_client = None
    
    yield
    
    # Shutdown
    log.info("Shutting down Entitlements Service V2")
    if redis_client:
        redis_client.close()

# Initialize FastAPI app with production middleware
app = FastAPI(
    title="ZeroQue Entitlements Service",
    description="Feature Access Control & Usage Tracking Service",
    version="2.0.0",
    lifespan=lifespan
)

# Production Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure appropriately for production
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Add observability middleware
add_observability_middleware(app, "entitlements")
add_api_call_meter(app)

# Custom Exceptions
class EntitlementValidationError(Exception):
    """Raised when entitlement validation fails"""
    pass

class EntitlementNotFoundError(Exception):
    """Raised when entitlement resource is not found"""
    pass

class UsageTrackingError(Exception):
    """Raised when usage tracking fails"""
    pass

# Exception Handlers
@app.exception_handler(EntitlementValidationError)
async def entitlement_validation_handler(request: Request, exc: EntitlementValidationError):
    raise HTTPException(status_code=400, detail=str(exc))

@app.exception_handler(EntitlementNotFoundError)
async def entitlement_not_found_handler(request: Request, exc: EntitlementNotFoundError):
    raise HTTPException(status_code=404, detail=str(exc))

@app.exception_handler(UsageTrackingError)
async def usage_tracking_handler(request: Request, exc: UsageTrackingError):
    raise HTTPException(status_code=500, detail=str(exc))

# Validation Helpers
def validate_uuid(uuid_string: str, field_name: str) -> str:
    """Validate UUID format"""
    try:
        uuid.UUID(uuid_string)
        return uuid_string
    except ValueError:
        raise EntitlementValidationError(f"Invalid {field_name} format: {uuid_string}")

def set_rls_context(db, tenant_id: Optional[str] = None, user_id: Optional[str] = None):
    """Set Row Level Security context for database session"""
    try:
        if tenant_id:
            db.execute(text("SET LOCAL app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        if user_id:
            db.execute(text("SET LOCAL app.user_id = :user_id"), {"user_id": user_id})
        
        # Enable RLS for the session
        db.execute(text("SET row_security = on"))
            
    except Exception as e:
        log.warning(f"Failed to set RLS context: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to set security context")

# Cache Management
async def get_cache(key: str) -> Optional[Dict[str, Any]]:
    """Get value from Redis cache"""
    global redis_client
    try:
        if not redis_client:
            redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        value = redis_client.get(key)
        if value:
            CACHE_HITS.labels(cache_type='entitlements').inc()
            return json.loads(value)
        else:
            CACHE_MISSES.labels(cache_type='entitlements').inc()
            return None
    except Exception as e:
        log.warning(f"Cache get error: {str(e)}")
        return None

async def set_cache(key: str, value: Dict[str, Any], ttl: int = 300) -> bool:
    """Set value in Redis cache with TTL"""
    global redis_client
    try:
        if not redis_client:
            redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        redis_client.setex(key, ttl, json.dumps(value))
        return True
    except Exception as e:
        log.warning(f"Cache set error: {str(e)}")
        return False

# Subscription Service Integration with Caching
async def get_tenant_subscription(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Get tenant subscription from subscriptions service with caching.
    """
    cache_key = f"subscription:{tenant_id}"
    
    # Try cache first
    cached = await get_cache(cache_key)
    if cached:
        return cached
    
    # Fallback to API call
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://localhost:8212/subscriptions/v2/subscriptions/{tenant_id}",
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                # Cache for 5 minutes
                await set_cache(cache_key, data, 300)
                return data
            elif response.status_code == 404:
                return None
            else:
                log.error(f"Failed to get subscription from subscriptions service: {response.status_code}")
                return None
    except Exception as e:
        log.error(f"Error calling subscriptions service: {str(e)}")
        return None

async def get_plan_features(plan_code: str) -> List[Dict[str, Any]]:
    """
    Get plan features from subscriptions service with caching.
    """
    cache_key = f"plan_features:{plan_code}"
    
    # Try cache first
    cached = await get_cache(cache_key)
    if cached:
        return cached.get("features", [])
    
    # Fallback to API call
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://localhost:8212/subscriptions/v2/plans/{plan_code}/features",
                timeout=5.0
            )
            if response.status_code == 200:
                data = response.json()
                # Cache for 1 hour (plan features don't change often)
                await set_cache(cache_key, data, 3600)
                return data.get("features", [])
            else:
                log.error(f"Failed to get plan features from subscriptions service: {response.status_code}")
                return []
    except Exception as e:
        log.error(f"Error calling subscriptions service for plan features: {str(e)}")
        return []

# Pydantic Models
class CheckEntitlementV2Request(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    feature_code: str = Field(..., description="Feature code to check")

class RecordUsageV2Request(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID")
    feature_code: str = Field(..., description="Feature code")
    usage_type: str = Field(..., description="Type of usage (e.g., api_calls, orders)")
    count: int = Field(..., description="Usage count")

# Health Endpoints
@app.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "ok", "service": "entitlements", "version": "2.0.0", "enhanced": True}

@app.get("/readiness")
async def readiness_check():
    """Readiness check with dependencies"""
    health_monitor = HealthMonitor("entitlements")
    system_health = await health_monitor.check_system_health()
    
    db_healthy = check_db()
    
    return {
        "service": "entitlements",
        "db": db_healthy,
        "system": system_health
    }

# Core Entitlement Endpoints
@app.get("/entitlements/v2/check")
async def check_entitlement_v2(
    tenant_id: str = Query(..., description="Tenant ID"),
    feature_code: str = Query(..., description="Feature code to check")
):
    """
    Check if tenant has access to a specific feature.
    """
    start_time = time.time()
    
    try:
        # Validate inputs
        validate_uuid(tenant_id, "tenant_id")
        
        # Get subscription from subscriptions service
        subscription = await get_tenant_subscription(tenant_id)
        
        if not subscription:
            ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='no_subscription').inc()
            return {
                "tenant_id": tenant_id,
                "feature_code": feature_code,
                "entitled": False,
                "enabled": False,
                "reason": "No active subscription found"
            }
        
        # Check if subscription is active
        if subscription.get("status") not in ["active", "trialing"]:
            ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='inactive_subscription').inc()
            return {
                "tenant_id": tenant_id,
                "feature_code": feature_code,
                "entitled": False,
                "enabled": False,
                "reason": f"Subscription status: {subscription.get('status')}"
            }
        
        # Get plan features from subscriptions service
        plan_code = subscription.get("plan_code")
        features = await get_plan_features(plan_code)
        
        # Check if feature is included in plan
        feature_found = None
        for feature in features:
            if feature.get("feature_code") == feature_code:
                feature_found = feature
                break
        
        if not feature_found:
            ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='feature_not_included').inc()
            return {
                "tenant_id": tenant_id,
                "feature_code": feature_code,
                "entitled": False,
                "enabled": False,
                "reason": f"Feature not included in plan: {plan_code}"
            }
        
        # Check usage limits if applicable
        limits = feature_found.get("limits", {})
        if limits:
            # Check current usage for this month
            db = SessionLocal()
            try:
                set_rls_context(db, tenant_id)
                
                # Get current month start and end
                now = datetime.now()
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                
                usage = db.query(SubscriptionUsage).filter(
                    SubscriptionUsage.tenant_id == tenant_id,
                    SubscriptionUsage.feature_code == feature_code,
                    SubscriptionUsage.period_start >= month_start,
                    SubscriptionUsage.period_start < month_end
                ).first()
                
                if usage and limits.get("rate_limit"):
                    if usage.usage_count >= limits["rate_limit"]:
                        ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='limit_exceeded').inc()
                        return {
                            "tenant_id": tenant_id,
                            "feature_code": feature_code,
                            "entitled": True,
                            "enabled": False,
                            "reason": f"Usage limit exceeded: {usage.usage_count}/{limits['rate_limit']}",
                            "usage": usage.usage_count,
                            "limit": limits["rate_limit"]
                        }
            finally:
                db.close()
        
        # Success case
        ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='enabled').inc()
        log.info("entitlement_checked", extra={
            "tenant": tenant_id,
            "feature": feature_code,
            "enabled": True,
            "plan_code": plan_code
        })
        
        return {
            "tenant_id": tenant_id,
            "feature_code": feature_code,
            "entitled": True,
            "enabled": True,
            "plan_code": plan_code,
            "limits": limits
        }
        
    except (EntitlementValidationError, EntitlementNotFoundError) as e:
        ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='validation_error').inc()
        raise e
    except SQLAlchemyError as e:
        ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='database_error').inc()
        log.error(f"Database error in check_entitlement: {str(e)}")
        raise UsageTrackingError(f"Database error: {str(e)}")
    except Exception as e:
        ENTITLEMENT_CHECKS.labels(tenant_id=tenant_id, feature_code=feature_code, result='internal_error').inc()
        log.error(f"Unexpected error in check_entitlement: {str(e)}")
        raise UsageTrackingError(f"Internal error: {str(e)}")
    finally:
        # Record timing metric
        ENTITLEMENT_CHECK_DURATION.observe(time.time() - start_time)

@app.post("/entitlements/v2/usage/record")
async def record_usage_v2(payload: RecordUsageV2Request = Body(...)):
    """
    Record usage for a tenant feature.
    """
    try:
        # Validate inputs
        validate_uuid(payload.tenant_id, "tenant_id")
        
        db = SessionLocal()
        try:
            set_rls_context(db, payload.tenant_id)
            
            # Get current month start and end
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            # Get or create usage record
            usage = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == payload.tenant_id,
                SubscriptionUsage.feature_code == payload.feature_code,
                SubscriptionUsage.usage_type == payload.usage_type,
                SubscriptionUsage.period_start >= month_start,
                SubscriptionUsage.period_start < month_end
            ).first()
            
            if usage:
                usage.usage_count += payload.count
                usage.updated_at = now
            else:
                usage = SubscriptionUsage(
                    tenant_id=payload.tenant_id,
                    feature_code=payload.feature_code,
                    usage_type=payload.usage_type,
                    usage_count=payload.count,
                    period_start=month_start,
                    period_end=month_end
                )
                db.add(usage)
            
            db.commit()
            
            log.info("usage_recorded", extra={
                "tenant": payload.tenant_id,
                "feature": payload.feature_code,
                "type": payload.usage_type,
                "count": payload.count,
                "total": usage.usage_count
            })
            
            return {
                "tenant_id": payload.tenant_id,
                "feature_code": payload.feature_code,
                "usage_type": payload.usage_type,
                "count": payload.count,
                "total": usage.usage_count,
                "period": now.strftime("%Y-%m")
            }
        except Exception as e:
            db.rollback()
            raise
        finally:
            db.close()
            
    except (EntitlementValidationError, EntitlementNotFoundError) as e:
        raise e
    except SQLAlchemyError as e:
        log.error(f"Database error in record_usage: {str(e)}")
        raise UsageTrackingError(f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in record_usage: {str(e)}")
        raise UsageTrackingError(f"Internal error: {str(e)}")

@app.get("/entitlements/v2/usage/{tenant_id}")
async def get_usage_summary_v2(tenant_id: str = Path(...)):
    """
    Get usage summary for a tenant.
    """
    try:
        # Validate inputs
        validate_uuid(tenant_id, "tenant_id")
        
        db = SessionLocal()
        try:
            set_rls_context(db, tenant_id)
            
            # Get current month usage
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            period = now.strftime("%Y-%m")
            
            usage_records = db.query(SubscriptionUsage).filter(
                SubscriptionUsage.tenant_id == tenant_id,
                SubscriptionUsage.period_start >= month_start,
                SubscriptionUsage.period_start < month_end
            ).all()
            
            usage_summary = {}
            for record in usage_records:
                key = f"{record.feature_code}:{record.usage_type}"
                usage_summary[key] = {
                    "feature_code": record.feature_code,
                    "usage_type": record.usage_type,
                    "count": record.usage_count,
                    "period": period
                }
        finally:
            db.close()
            
        log.info("usage_summary_retrieved", extra={
            "tenant": tenant_id,
            "period": period
        })
        
        return {
            "tenant_id": tenant_id,
            "period": period,
            "usage": usage_summary
        }

    except (EntitlementValidationError, EntitlementNotFoundError) as e:
        raise e
    except SQLAlchemyError as e:
        log.error(f"Database error in get_usage: {str(e)}")
        raise UsageTrackingError(f"Database error: {str(e)}")
    except Exception as e:
        log.error(f"Unexpected error in get_usage: {str(e)}")
        raise UsageTrackingError(f"Internal error: {str(e)}")

# Metrics endpoint
@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint"""
    return generate_latest()

# Cache management endpoints
@app.post("/entitlements/v2/cache/clear")
async def clear_cache_v2(
    tenant_id: Optional[str] = Query(None, description="Tenant ID to clear cache for"),
    cache_type: Optional[str] = Query(None, description="Cache type to clear")
):
    """
    Clear cache entries.
    """
    try:
        global redis_client
        if not redis_client:
            raise HTTPException(status_code=503, detail="Cache not available")
        
        if tenant_id:
            # Clear specific tenant cache
            pattern = f"subscription:{tenant_id}"
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)
            
            log.info("cache_cleared", extra={"tenant_id": tenant_id, "keys_cleared": len(keys)})
            return {"cleared": True, "tenant_id": tenant_id, "keys_cleared": len(keys)}
        else:
            # Clear all cache
            redis_client.flushdb()
            log.info("cache_cleared_all")
            return {"cleared": True, "message": "All cache cleared"}
            
    except Exception as e:
        log.error(f"Cache clear error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Cache clear failed: {str(e)}")

# Main execution
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8211)
