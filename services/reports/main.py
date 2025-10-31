#!/usr/bin/env python3
"""
ZeroQue Reports Service V4.1
Comprehensive analytics, reporting, and business intelligence platform
"""
import uuid
import os
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import text
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import pybreaker
from sqlalchemy.orm import Session
from sqlalchemy.util import await_only

from core.config import get_settings
from .utils.reports_logger import logger
from .models import Dashboard, DashboardAccess
from .utils.report_enums import DashboardType
from .schemas import ReportRequest, ReportResponse, DashboardCreateRequest, DashboardResponse, \
    PowerBIEmbedResponse, PowerBIEmbedRequest, DashboardDataRefresh
from .repositories.report_generator_saga import ReportGenerator
from .repositories.db_config import SessionLocal, get_db
from .utils.metrics import report_requests_total, report_generation_duration
from .services.reports_services import generate_report, fetch_report_status, download_report, get_sales_analytics, \
    get_inventory_analytics, get_customer_analytics, get_operational_analytics, create_dashboard, list_dashboards, \
    get_dashboard, generate_embed_token_service, refresh_dashboard_data_service, get_refresh_status

# Service configuration
SERVICE_NAME = "reports"
SERVICE_VERSION = "4.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# ---- Application Setup ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME}", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    yield
    
    logger.info(f"Shutting down {SERVICE_NAME}")

app = FastAPI(
    title=f"ZeroQue {SERVICE_NAME.title()} Service V4.1",
    description="Comprehensive analytics, reporting, and business intelligence platform",
    version=SERVICE_VERSION,
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
        "version": SERVICE_VERSION,
        "environment": ENVIRONMENT
    }

@app.get("/readiness")
async def readiness(db=Depends(get_db)):
    """Readiness check endpoint"""
    try:
        db.execute(text("SELECT 1"))
        return {
            "service": SERVICE_NAME,
            "status": "ready",
            "database": "connected"
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service not ready: {str(e)}")

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ---- Report Generation Endpoints ----
@app.post("/reports/v4/generate", response_model=ReportResponse)
async def generate_report_route(request: ReportRequest, background_tasks: BackgroundTasks, db: Session=Depends(get_db)):
    """Generate a new report"""
    return await generate_report(request, background_tasks, db)

@app.get("/reports/v4/status/{job_id}")
async def get_report_status(job_id: str, db:Session=Depends(get_db)):
    """Get report generation status"""
    return await fetch_report_status(job_id, db)

@app.get("/reports/v4/download/{job_id}")
async def download_report_route(job_id: str, db: Session=Depends(get_db)):
    """Download completed report"""
    return await download_report(job_id, db)

# ---- Analytics Endpoints ----
@app.get("/analytics/v4/sales")
async def get_sales_analytics_route(tenant_id: str = Query(...), start_date: str = Query(...), end_date: str = Query(...),
                              store_id: Optional[str] = Query(None), group_by: str = Query("day"), db: Session=Depends(get_db)):
    """Get sales analytics data"""
    return await get_sales_analytics(tenant_id, start_date, end_date, store_id, group_by, db)

@app.get("/analytics/v4/inventory")
async def get_inventory_analytics_route(tenant_id: str = Query(...), store_id: Optional[str] = Query(None),
                                  db: Session=Depends(get_db)):
    """Get inventory analytics data"""
    return await get_inventory_analytics(tenant_id, store_id, db)

@app.get("/analytics/v4/customers")
async def get_customer_analytics_route(tenant_id: str = Query(...), start_date: str = Query(...), end_date: str = Query(...),
                                 db: Session=Depends(get_db)):
    """Get customer analytics data"""
    return await get_customer_analytics(tenant_id, start_date, end_date, db)

@app.get("/analytics/v4/operational")
async def get_operational_analytics_route(tenant_id: str = Query(...), start_date: str = Query(...),
                                    end_date: str = Query(...), db: Session=Depends(get_db)):
    """Get operational analytics data"""
    return await get_operational_analytics(tenant_id, start_date, end_date, db)

# Phase 6: Dashboard Management Endpoints (Power BI Integration)
@app.post("/dashboards", response_model=DashboardResponse)
async def create_dashboard_route(request: DashboardCreateRequest, tenant_id: str = Query(...),
                                 user_id: str = Query(...), db: Session=Depends(get_db)):
    """Create a new dashboard - Phase 6"""
    return await create_dashboard(request, tenant_id, user_id, db)

@app.get("/dashboards")
async def list_dashboards_route(tenant_id: str = Query(...), dashboard_type: Optional[str] = Query(None),
                          user_id: str = Query(...), db: Session=Depends(get_db)):
    """List dashboards for tenant - Phase 6"""
    return await list_dashboards(tenant_id, dashboard_type, db)

@app.get("/dashboards/{dashboard_id}")
async def get_dashboard_route(dashboard_id: str, tenant_id: str = Query(...), user_id: str = Query(...), db: Session=Depends(get_db)):
    """Get dashboard details - Phase 6"""
    return await get_dashboard(dashboard_id, tenant_id, user_id, db)

@app.post("/dashboards/{dashboard_id}/embed-token", response_model=PowerBIEmbedResponse)
async def generate_embed_token(dashboard_id: str, request: PowerBIEmbedRequest, tenant_id: str = Query(...),
                               user_id: str = Query(...), db: Session=Depends(get_db)
):
    """Generate Power BI embed token - Phase 6"""
    return await generate_embed_token_service(dashboard_id, request, tenant_id, user_id, db)

@app.post("/dashboards/{dashboard_id}/refresh")
async def refresh_dashboard_data( dashboard_id: str, tenant_id: str = Query(...), user_id: str = Query(...),
                                  db: Session=Depends(get_db)):
    """Trigger dashboard data refresh - Phase 6"""
    return await refresh_dashboard_data_service(dashboard_id, tenant_id, user_id, db)

@app.get("/dashboards/{dashboard_id}/refresh-status")
async def get_refresh_status_route(dashboard_id: str, db: Session=Depends(get_db)):
    """Get dashboard refresh status - Phase 6"""
    return await get_refresh_status(dashboard_id, db)

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8227")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )