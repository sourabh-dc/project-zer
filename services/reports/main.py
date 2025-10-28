#!/usr/bin/env python3
"""
ZeroQue Reports Service V4.1
Comprehensive analytics, reporting, and business intelligence platform
"""
import uuid
import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import pandas as pd
import io
import redis
import pybreaker

from core.config import get_settings
from .utils.reports_logger import logger
from .models import ReportJob, Dashboard, DashboardAccess
from .utils.report_enums import ReportType, ReportFormat, ReportStatus, DashboardType
from .schemas import ReportRequest, ReportResponse, DashboardCreateRequest, DashboardResponse, \
    PowerBIEmbedResponse, PowerBIEmbedRequest, DashboardDataRefresh
from .repositories.report_generator_saga import ReportGenerator
from .repositories.db_config import SessionLocal
from .utils.metrics import report_requests_total, report_generation_duration

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
async def readiness():
    """Readiness check endpoint"""
    try:
        with SessionLocal() as db:
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
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ---- Report Generation Endpoints ----
@app.post("/reports/v4/generate", response_model=ReportResponse)
async def generate_report(request: ReportRequest, background_tasks: BackgroundTasks):
    """Generate a new report"""
    try:
        job_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{request.report_type}"
        
        # Check cache first
        cache_key = f"{request.tenant_id}:{request.report_type}:{hash(str(request.parameters))}"
        
        with SessionLocal() as db:
            # Create report job
            job = ReportJob(
                id=job_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                report_type=request.report_type,
                report_name=request.report_name,
                parameters=request.parameters,
                status=ReportStatus.GENERATING,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
            )
            db.add(job)
            db.commit()
            
            # Start background report generation
            background_tasks.add_task(
                generate_report_background,
                job_id,
                request.report_type,
                request.parameters,
                request.format,
                request.cache_ttl_minutes
            )
        
        report_requests_total.labels(report_type=request.report_type, status="initiated").inc()
        
        return ReportResponse(
            job_id=job_id,
            status=ReportStatus.GENERATING,
            message="Report generation initiated",
            estimated_completion=datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        
    except Exception as e:
        logger.error("Failed to initiate report generation", error=str(e))
        report_requests_total.labels(report_type=request.report_type, status="failed").inc()
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")

@app.get("/reports/v4/status/{job_id}")
async def get_report_status(job_id: str):
    """Get report generation status"""
    try:
        with SessionLocal() as db:
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if not job:
                raise HTTPException(status_code=404, detail="Report job not found")
            
            return {
                "job_id": job.id,
                "status": job.status,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "error_message": job.error_message,
                "file_path": job.file_path
            }
    except Exception as e:
        logger.error("Failed to get report status", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/reports/v4/download/{job_id}")
async def download_report(job_id: str):
    """Download completed report"""
    try:
        with SessionLocal() as db:
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if not job:
                raise HTTPException(status_code=404, detail="Report job not found")
            
            if job.status != ReportStatus.COMPLETED:
                raise HTTPException(status_code=400, detail="Report not ready for download")
            
            if not job.file_path or not os.path.exists(job.file_path):
                raise HTTPException(status_code=404, detail="Report file not found")
            
            # Return file based on format
            with open(job.file_path, 'rb') as f:
                content = f.read()
            
            return StreamingResponse(
                io.BytesIO(content),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={job.report_name}.{job.parameters.get('format', 'json')}"}
            )
            
    except Exception as e:
        logger.error("Failed to download report", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# ---- Analytics Endpoints ----
@app.get("/analytics/v4/sales")
async def get_sales_analytics(
    tenant_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    store_id: Optional[str] = Query(None),
    group_by: str = Query("day")
):
    """Get sales analytics data"""
    try:
        start_time = datetime.now()
        
        with SessionLocal() as db:
            generator = ReportGenerator(db)
            params = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
                "store_id": store_id,
                "group_by": group_by
            }
            
            data = await generator.generate_sales_analytics(params)
        
        duration = (datetime.now() - start_time).total_seconds()
        report_generation_duration.labels(report_type="sales_analytics").observe(duration)
        report_requests_total.labels(report_type="sales_analytics", status="success").inc()
        
        return {
            "data": data,
            "generated_at": datetime.now(timezone.utc),
            "generation_time_seconds": duration
        }
        
    except Exception as e:
        logger.error("Failed to generate sales analytics", error=str(e))
        report_requests_total.labels(report_type="sales_analytics", status="failed").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/v4/inventory")
async def get_inventory_analytics(
    tenant_id: str = Query(...),
    store_id: Optional[str] = Query(None)
):
    """Get inventory analytics data"""
    try:
        start_time = datetime.now()
        
        with SessionLocal() as db:
            generator = ReportGenerator(db)
            params = {
                "tenant_id": tenant_id,
                "store_id": store_id
            }
            
            data = await generator.generate_inventory_analytics(params)
        
        duration = (datetime.now() - start_time).total_seconds()
        report_generation_duration.labels(report_type="inventory_analytics").observe(duration)
        report_requests_total.labels(report_type="inventory_analytics", status="success").inc()
        
        return {
            "data": data,
            "generated_at": datetime.now(timezone.utc),
            "generation_time_seconds": duration
        }
        
    except Exception as e:
        logger.error("Failed to generate inventory analytics", error=str(e))
        report_requests_total.labels(report_type="inventory_analytics", status="failed").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/v4/customers")
async def get_customer_analytics(
    tenant_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...)
):
    """Get customer analytics data"""
    try:
        start_time = datetime.now()
        
        with SessionLocal() as db:
            generator = ReportGenerator(db)
            params = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date
            }
            
            data = await generator.generate_customer_analytics(params)
        
        duration = (datetime.now() - start_time).total_seconds()
        report_generation_duration.labels(report_type="customer_analytics").observe(duration)
        report_requests_total.labels(report_type="customer_analytics", status="success").inc()
        
        return {
            "data": data,
            "generated_at": datetime.now(timezone.utc),
            "generation_time_seconds": duration
        }
        
    except Exception as e:
        logger.error("Failed to generate customer analytics", error=str(e))
        report_requests_total.labels(report_type="customer_analytics", status="failed").inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/v4/operational")
async def get_operational_analytics(
    tenant_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...)
):
    """Get operational analytics data"""
    try:
        start_time = datetime.now()
        
        with SessionLocal() as db:
            generator = ReportGenerator(db)
            params = {
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date
            }
            
            data = await generator.generate_operational_analytics(params)
        
        duration = (datetime.now() - start_time).total_seconds()
        report_generation_duration.labels(report_type="operational_analytics").observe(duration)
        report_requests_total.labels(report_type="operational_analytics", status="success").inc()
        
        return {
            "data": data,
            "generated_at": datetime.now(timezone.utc),
            "generation_time_seconds": duration
        }
        
    except Exception as e:
        logger.error("Failed to generate operational analytics", error=str(e))
        report_requests_total.labels(report_type="operational_analytics", status="failed").inc()
        raise HTTPException(status_code=500, detail=str(e))

# Phase 6: Dashboard Management Endpoints (Power BI Integration)
@app.post("/dashboards", response_model=DashboardResponse)
async def create_dashboard(
    request: DashboardCreateRequest,
    tenant_id: str = Query(...),
    user_id: str = Query(...)
):
    """Create a new dashboard - Phase 6"""
    try:
        start_time = datetime.now()

        with SessionLocal() as db:
            # Check if dashboard name already exists for tenant
            existing = db.query(Dashboard).filter(
                Dashboard.tenant_id == tenant_id,
                Dashboard.name == request.name
            ).first()

            if existing:
                raise HTTPException(status_code=409, detail="Dashboard name already exists")

            # Create dashboard
            dashboard_id = str(uuid.uuid4())
            dashboard = Dashboard(
                dashboard_id=dashboard_id,
                tenant_id=tenant_id,
                name=request.name,
                description=request.description,
                dashboard_type=request.dashboard_type.value,
                powerbi_workspace_id=request.powerbi_workspace_id,
                powerbi_report_id=request.powerbi_report_id,
                powerbi_dataset_id=request.powerbi_dataset_id,
                embed_config=request.embed_config,
                data_sources=request.data_sources,
                refresh_schedule=request.refresh_schedule,
                filters=request.filters,
                is_public=request.is_public
            )

            db.add(dashboard)

            # Create default access for creator
            access_id = str(uuid.uuid4())
            access = DashboardAccess(
                id=access_id,
                dashboard_id=dashboard_id,
                user_id=user_id,
                permissions=["read", "write", "admin"]  # Full access for creator
            )
            db.add(access)

            # Create initial data refresh record
            refresh_id = str(uuid.uuid4())
            refresh = DashboardDataRefresh(
                id=refresh_id,
                dashboard_id=dashboard_id,
                status="pending"
            )
            db.add(refresh)

            db.commit()

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Dashboard created: {dashboard_id} for tenant {tenant_id}")

        return DashboardResponse(
            dashboard_id=dashboard_id,
            name=request.name,
            description=request.description,
            dashboard_type=request.dashboard_type,
            powerbi_workspace_id=request.powerbi_workspace_id,
            powerbi_report_id=request.powerbi_report_id,
            powerbi_dataset_id=request.powerbi_dataset_id,
            embed_config=request.embed_config,
            data_sources=request.data_sources,
            refresh_schedule=request.refresh_schedule,
            filters=request.filters,
            is_public=request.is_public,
            created_at=dashboard.created_at,
            updated_at=dashboard.updated_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboards")
async def list_dashboards(
    tenant_id: str = Query(...),
    dashboard_type: Optional[str] = Query(None),
    user_id: str = Query(...)
):
    """List dashboards for tenant - Phase 6"""
    try:
        with SessionLocal() as db:
            query = db.query(Dashboard).filter(
                Dashboard.tenant_id == tenant_id
            )

            if dashboard_type:
                query = query.filter(Dashboard.dashboard_type == dashboard_type)

            dashboards = query.all()

            return {
                "dashboards": [
                    {
                        "dashboard_id": d.dashboard_id,
                        "name": d.name,
                        "description": d.description,
                        "dashboard_type": d.dashboard_type,
                        "is_public": d.is_public,
                        "created_at": d.created_at.isoformat(),
                        "updated_at": d.updated_at.isoformat() if d.updated_at else None
                    }
                    for d in dashboards
                ],
                "total": len(dashboards)
            }

    except Exception as e:
        logger.error(f"Failed to list dashboards: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboards/{dashboard_id}")
async def get_dashboard(
    dashboard_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...)
):
    """Get dashboard details - Phase 6"""
    try:
        with SessionLocal() as db:
            dashboard = db.query(Dashboard).filter(
                Dashboard.dashboard_id == dashboard_id,
                Dashboard.tenant_id == tenant_id
            ).first()

            if not dashboard:
                raise HTTPException(status_code=404, detail="Dashboard not found")

            # Check access permissions (simplified - in production, check against DashboardAccess table)
            return DashboardResponse(
                dashboard_id=dashboard.dashboard_id,
                name=dashboard.name,
                description=dashboard.description,
                dashboard_type=DashboardType(dashboard.dashboard_type),
                powerbi_workspace_id=dashboard.powerbi_workspace_id,
                powerbi_report_id=dashboard.powerbi_report_id,
                powerbi_dataset_id=dashboard.powerbi_dataset_id,
                embed_config=dashboard.embed_config,
                data_sources=dashboard.data_sources,
                refresh_schedule=dashboard.refresh_schedule,
                filters=dashboard.filters,
                is_public=dashboard.is_public,
                created_at=dashboard.created_at,
                updated_at=dashboard.updated_at
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dashboards/{dashboard_id}/embed-token", response_model=PowerBIEmbedResponse)
async def generate_embed_token(
    dashboard_id: str,
    request: PowerBIEmbedRequest,
    tenant_id: str = Query(...),
    user_id: str = Query(...)
):
    """Generate Power BI embed token - Phase 6"""
    try:
        with SessionLocal() as db:
            dashboard = db.query(Dashboard).filter(
                Dashboard.dashboard_id == dashboard_id,
                Dashboard.tenant_id == tenant_id
            ).first()

            if not dashboard:
                raise HTTPException(status_code=404, detail="Dashboard not found")

            # Check access permissions (simplified)
            # In production: verify user has access to dashboard

            # Generate mock Power BI embed token (in production, integrate with Power BI API)
            import secrets
            embed_token = secrets.token_urlsafe(64)
            embed_url = f"https://app.powerbi.com/reportEmbed?reportId={dashboard.powerbi_report_id}&groupId={dashboard.powerbi_workspace_id}"
            expiry = datetime.now(timezone.utc) + timedelta(hours=1)

            return PowerBIEmbedResponse(
                embed_token=embed_token,
                embed_url=embed_url,
                expiry=expiry,
                permissions=request.permissions
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate embed token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dashboards/{dashboard_id}/refresh")
async def refresh_dashboard_data(
    dashboard_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...)
):
    """Trigger dashboard data refresh - Phase 6"""
    try:
        with SessionLocal() as db:
            dashboard = db.query(Dashboard).filter(
                Dashboard.dashboard_id == dashboard_id,
                Dashboard.tenant_id == tenant_id
            ).first()

            if not dashboard:
                raise HTTPException(status_code=404, detail="Dashboard not found")

            # Update refresh status
            refresh = db.query(DashboardDataRefresh).filter(
                DashboardDataRefresh.dashboard_id == dashboard_id
            ).first()

            if refresh:
                refresh.status = "running"
                refresh.updated_at = datetime.now(timezone.utc)
                db.commit()

            # In production: trigger actual data refresh from data sources
            # For now, just mark as completed after a delay (simulate async refresh)
            await asyncio.sleep(2)  # Simulate refresh time

            if refresh:
                refresh.status = "completed"
                refresh.last_refresh = datetime.now(timezone.utc)
                refresh.updated_at = datetime.now(timezone.utc)
                db.commit()

            logger.info(f"Dashboard data refresh completed: {dashboard_id}")

            return {"message": "Dashboard data refresh completed", "dashboard_id": dashboard_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to refresh dashboard data: {e}")
        # Mark refresh as failed
        try:
            with SessionLocal() as db:
                refresh = db.query(DashboardDataRefresh).filter(
                    DashboardDataRefresh.dashboard_id == dashboard_id
                ).first()
                if refresh:
                    refresh.status = "failed"
                    refresh.error_message = str(e)
                    refresh.updated_at = datetime.now(timezone.utc)
                    db.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dashboards/{dashboard_id}/refresh-status")
async def get_refresh_status(
    dashboard_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...)
):
    """Get dashboard refresh status - Phase 6"""
    try:
        with SessionLocal() as db:
            refresh = db.query(DashboardDataRefresh).filter(
                DashboardDataRefresh.dashboard_id == dashboard_id
            ).first()

            if not refresh:
                raise HTTPException(status_code=404, detail="Refresh status not found")

            return DashboardDataRefresh(
                dashboard_id=refresh.dashboard_id,
                status=refresh.status,
                last_refresh=refresh.last_refresh,
                next_refresh=refresh.next_refresh,
                error_message=refresh.error_message
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get refresh status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---- Background Tasks ----
async def generate_report_background(job_id: str, report_type: str, parameters: Dict[str, Any], format: ReportFormat, cache_ttl_minutes: int):
    """Background task to generate reports"""
    try:
        with SessionLocal() as db:
            generator = ReportGenerator(db)
            
            # Generate report data based on type
            if report_type == ReportType.SALES_ANALYTICS:
                data = await generator.generate_sales_analytics(parameters)
            elif report_type == ReportType.INVENTORY_ANALYTICS:
                data = await generator.generate_inventory_analytics(parameters)
            elif report_type == ReportType.CUSTOMER_ANALYTICS:
                data = await generator.generate_customer_analytics(parameters)
            elif report_type == ReportType.OPERATIONAL_ANALYTICS:
                data = await generator.generate_operational_analytics(parameters)
            else:
                raise ValueError(f"Unsupported report type: {report_type}")
            
            # Save report data to file
            file_path = f"/tmp/reports/{job_id}.{format}"
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            if format == ReportFormat.JSON:
                with open(file_path, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
            elif format == ReportFormat.CSV:
                # Convert to CSV format (simplified)
                df = pd.json_normalize(data)
                df.to_csv(file_path, index=False)
            
            # Update job status
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if job:
                job.status = ReportStatus.COMPLETED
                job.file_path = file_path
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
            
            logger.info("Report generation completed", job_id=job_id, report_type=report_type)
            
    except Exception as e:
        logger.error("Report generation failed", job_id=job_id, error=str(e))
        
        # Update job status to failed
        try:
            with SessionLocal() as db:
                job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
                if job:
                    job.status = ReportStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception:
            pass

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