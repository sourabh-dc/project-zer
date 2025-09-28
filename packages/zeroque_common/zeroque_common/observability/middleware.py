# packages/zeroque_common/zeroque_common/observability/middleware.py
"""
Observability middleware for ZeroQue services
"""
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .logging import ZeroQueLogger
from .metrics import get_metrics, counter, gauge, histogram
from .insights import get_insights

class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically collect observability data"""
    
    def __init__(self, app: ASGIApp, service_name: str):
        super().__init__(app)
        self.service_name = service_name
        self.logger = ZeroQueLogger(f"middleware.{service_name}", service_name)
        
        # Metrics
        self.request_counter = counter("http_requests_total", {"service": service_name})
        self.request_duration = histogram("http_request_duration_seconds", {"service": service_name})
        self.active_requests = gauge("http_active_requests", {"service": service_name})
        self.error_counter = counter("http_errors_total", {"service": service_name})
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Extract context
        tenant_id = request.headers.get("X-Tenant-ID")
        user_id = request.headers.get("X-User-ID")
        site_id = request.headers.get("X-Site-ID")
        store_id = request.headers.get("X-Store-ID")
        
        # Start timing
        start_time = time.time()
        self.active_requests.inc()
        
        # Log request start
        self.logger.info(f"Request started: {request.method} {request.url.path}",
                        request_id=request_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        site_id=site_id,
                        store_id=store_id,
                        method=request.method,
                        path=request.url.path)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Record metrics
            self.request_counter.inc()
            self.request_duration.observe(duration)
            
            # Log successful request
            self.logger.info(f"Request completed: {request.method} {request.url.path}",
                           request_id=request_id,
                           tenant_id=tenant_id,
                           user_id=user_id,
                           site_id=site_id,
                           store_id=store_id,
                           method=request.method,
                           path=request.url.path,
                           status_code=response.status_code,
                           duration_ms=duration * 1000)
            
            # Record business events based on endpoint
            await self._record_business_events(request, response, tenant_id, user_id, site_id, store_id)
            
            return response
            
        except Exception as e:
            # Calculate duration
            duration = time.time() - start_time
            
            # Record error metrics
            self.error_counter.inc()
            self.request_duration.observe(duration)
            
            # Log error
            self.logger.error(f"Request failed: {request.method} {request.url.path}",
                             request_id=request_id,
                             tenant_id=tenant_id,
                             user_id=user_id,
                             site_id=site_id,
                             store_id=store_id,
                             method=request.method,
                             path=request.url.path,
                             duration_ms=duration * 1000,
                             error=str(e))
            
            # Record error in insights
            insights = get_insights()
            insights.record_error("http_request_error", str(e),
                                request_id=request_id,
                                tenant_id=tenant_id,
                                method=request.method,
                                path=request.url.path)
            
            raise
        
        finally:
            self.active_requests.dec()
    
    async def _record_business_events(self, request: Request, response: Response, 
                                    tenant_id: str, user_id: str, site_id: str, store_id: str):
        """Record business events based on the endpoint"""
        insights = get_insights()
        
        # Order events
        if request.url.path.startswith("/orders") and request.method == "POST":
            if response.status_code == 200:
                insights.record_business_event("orders_created", 1.0,
                                            tenant_id=tenant_id, user_id=user_id, site_id=site_id, store_id=store_id)
        
        # Entry events
        elif request.url.path.startswith("/entry/issue-code") and request.method == "POST":
            if response.status_code == 200:
                insights.record_business_event("entry_codes_generated", 1.0,
                                            tenant_id=tenant_id, user_id=user_id, site_id=site_id, store_id=store_id)
        
        # Product events
        elif request.url.path.startswith("/products") and request.method == "POST":
            if response.status_code == 200:
                insights.record_business_event("products_created", 1.0,
                                            tenant_id=tenant_id, user_id=user_id, site_id=site_id, store_id=store_id)

def add_observability_middleware(app, service_name: str):
    """Add observability middleware to a FastAPI app"""
    app.add_middleware(ObservabilityMiddleware, service_name=service_name)
