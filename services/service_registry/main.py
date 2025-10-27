#!/usr/bin/env python3
"""
ZeroQue Service Registry V4.1
Centralized service discovery and health monitoring
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from .schemas import ServiceInfo, ServiceRegistryResponse
from .utils.service_registry_logger import logger
from .services import update_service_registry, periodic_registry_update


# Service configuration
SERVICE_NAME = "service-registry"
VERSION = "4.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Global service registry
service_registry: Dict[str, ServiceInfo] = {}

# Application setup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME}", version=VERSION, environment=ENVIRONMENT)
    
    # Initial service registry update
    await update_service_registry()
    
    # Start background task for periodic updates
    task = asyncio.create_task(periodic_registry_update())
    
    yield
    
    # Cleanup
    task.cancel()
    logger.info(f"Shutting down {SERVICE_NAME}")

app = FastAPI(
    title=f"ZeroQue {SERVICE_NAME.title()} V4.1",
    description="Centralized service discovery and health monitoring",
    version=VERSION,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Health Endpoints ----
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "environment": ENVIRONMENT
    }

@app.get("/readiness")
async def readiness():
    """Readiness check endpoint"""
    healthy_count = sum(1 for s in service_registry.values() if s.status == "healthy")
    total_count = len(service_registry)
    
    if healthy_count >= total_count * 0.8:  # 80% healthy threshold
        return {
            "service": SERVICE_NAME,
            "status": "ready",
            "healthy_services": healthy_count,
            "total_services": total_count
        }
    else:
        raise HTTPException(status_code=503, detail="Service registry not ready")

# ---- Service Discovery Endpoints ----
@app.get("/services", response_model=ServiceRegistryResponse)
async def get_services():
    """Get all services with their current status"""
    services_list = list(service_registry.values())
    healthy_count = sum(1 for s in services_list if s.status == "healthy")
    unhealthy_count = len(services_list) - healthy_count
    
    return ServiceRegistryResponse(
        services=services_list,
        total_services=len(services_list),
        healthy_services=healthy_count,
        unhealthy_services=unhealthy_count,
        last_updated=datetime.now(timezone.utc)
    )

@app.get("/services/{service_name}")
async def get_service(service_name: str):
    """Get specific service information"""
    if service_name not in service_registry:
        raise HTTPException(status_code=404, detail="Service not found")
    
    return service_registry[service_name]

@app.post("/services/refresh")
async def refresh_services(background_tasks: BackgroundTasks):
    """Manually refresh service registry"""
    background_tasks.add_task(update_service_registry)
    return {"message": "Service registry refresh initiated"}

@app.get("/services/healthy")
async def get_healthy_services():
    """Get only healthy services"""
    healthy_services = [s for s in service_registry.values() if s.status == "healthy"]
    return {
        "services": healthy_services,
        "count": len(healthy_services)
    }

@app.get("/services/unhealthy")
async def get_unhealthy_services():
    """Get only unhealthy services"""
    unhealthy_services = [s for s in service_registry.values() if s.status != "healthy"]
    return {
        "services": unhealthy_services,
        "count": len(unhealthy_services)
    }

# ---- Service Discovery Integration ----
@app.get("/discovery/{service_name}/endpoints")
async def get_service_endpoints(service_name: str):
    """Get available endpoints for a service"""
    if service_name not in service_registry:
        raise HTTPException(status_code=404, detail="Service not found")
    
    service = service_registry[service_name]
    
    # Common endpoints for each service type
    endpoints = {
        "cv_gateway": ["/health", "/cv/webhook/order", "/cv/entry/codes"],
        "orders": ["/health", "/orders/v2", "/orders/v2/integration/status"],
        "identity": ["/health", "/users/v4", "/roles/v4"],
        "ledger": ["/health", "/ledger/v2/entries", "/ledger/v2/balances"],
        "payments": ["/health", "/payments/v2/intent", "/payments/v2/transactions"],
        "events": ["/events/v4/health", "/events/v4/publish", "/events/v4/history"],
        "cv_connector": ["/health", "/cv/sync/users", "/cv/sync/products"],
        "entitlements": ["/health", "/entitlements/v2/check", "/entitlements/v2/usage"],
        "subscriptions": ["/health", "/subscriptions/v2/plans", "/subscriptions/v2/subscriptions"],
        "approvals": ["/health", "/approvals/v2/requests", "/approvals/v2/chains"],
        "notifications": ["/health", "/notifications/v4/send", "/notifications/v4/history"],
    }
    
    return {
        "service": service_name,
        "base_url": f"http://localhost:{service.port}",
        "endpoints": endpoints.get(service_name, ["/health"]),
        "status": service.status
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8500")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )

