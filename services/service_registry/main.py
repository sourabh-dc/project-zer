#!/usr/bin/env python3
"""
ZeroQue Service Registry V4.1
Centralized service discovery and health monitoring
"""

import os
import json
import asyncio
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Service configuration
SERVICE_NAME = "service-registry"
VERSION = "4.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Service registry configuration
SERVICES = {
    "cv_gateway": {"port": 8000, "health_path": "/health", "version": "4.1.0"},
    "orders": {"port": 8080, "health_path": "/health", "version": "2.0.0"},
    "identity": {"port": 8085, "health_path": "/health", "version": "4.1.0"},
    "ledger": {"port": 8086, "health_path": "/health", "version": "2.0.0"},
    "payments": {"port": 8087, "health_path": "/health", "version": "2.0.0"},
    "events": {"port": 8088, "health_path": "/events/v4/health", "version": "2.0.0"},
    "cv_connector": {"port": 8100, "health_path": "/health", "version": "4.1.0"},
    "entitlements": {"port": 8211, "health_path": "/health", "version": "2.0.0"},
    "subscriptions": {"port": 8212, "health_path": "/health", "version": "2.0.0"},
    "approvals": {"port": 8213, "health_path": "/health", "version": "2.0.0"},
    "notifications": {"port": 8300, "health_path": "/health", "version": "4.1.0"},
}

# Pydantic models
class ServiceInfo(BaseModel):
    name: str
    port: int
    status: str
    version: str
    last_check: datetime
    response_time_ms: Optional[float] = None
    error: Optional[str] = None

class ServiceRegistryResponse(BaseModel):
    services: List[ServiceInfo]
    total_services: int
    healthy_services: int
    unhealthy_services: int
    last_updated: datetime

# Global service registry
service_registry: Dict[str, ServiceInfo] = {}

async def check_service_health(service_name: str, config: Dict[str, Any]) -> ServiceInfo:
    """Check health of a single service"""
    start_time = datetime.now()
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://localhost:{config['port']}{config['health_path']}")
            
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                status = "healthy"
                if isinstance(data, dict):
                    status = data.get("status", "healthy")
                
                return ServiceInfo(
                    name=service_name,
                    port=config["port"],
                    status=status,
                    version=config["version"],
                    last_check=datetime.now(timezone.utc),
                    response_time_ms=response_time
                )
            else:
                return ServiceInfo(
                    name=service_name,
                    port=config["port"],
                    status="unhealthy",
                    version=config["version"],
                    last_check=datetime.now(timezone.utc),
                    response_time_ms=response_time,
                    error=f"HTTP {response.status_code}"
                )
                
    except Exception as e:
        response_time = (datetime.now() - start_time).total_seconds() * 1000
        return ServiceInfo(
            name=service_name,
            port=config["port"],
            status="unreachable",
            version=config["version"],
            last_check=datetime.now(timezone.utc),
            response_time_ms=response_time,
            error=str(e)
        )

async def update_service_registry():
    """Update the service registry with current health status"""
    global service_registry
    
    logger.info("Updating service registry")
    
    # Check all services concurrently
    tasks = []
    for service_name, config in SERVICES.items():
        task = check_service_health(service_name, config)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Update registry
    for i, result in enumerate(results):
        service_name = list(SERVICES.keys())[i]
        if isinstance(result, Exception):
            service_registry[service_name] = ServiceInfo(
                name=service_name,
                port=SERVICES[service_name]["port"],
                status="error",
                version=SERVICES[service_name]["version"],
                last_check=datetime.now(timezone.utc),
                error=str(result)
            )
        else:
            service_registry[service_name] = result
    
    logger.info("Service registry updated", 
                total_services=len(service_registry),
                healthy_services=sum(1 for s in service_registry.values() if s.status == "healthy"))

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

async def periodic_registry_update():
    """Periodically update service registry"""
    while True:
        try:
            await asyncio.sleep(30)  # Update every 30 seconds
            await update_service_registry()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic registry update", error=str(e))

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

