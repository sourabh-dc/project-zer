#!/usr/bin/env python3
"""
ZeroQue Reports Service V4.1
Comprehensive analytics, reporting, and business intelligence platform
"""

import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union
from contextlib import asynccontextmanager
from enum import Enum

import structlog
from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, func, and_, or_, Column, String, DateTime, Integer, JSON, Boolean, Text, ForeignKey, Numeric
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.exc import SQLAlchemyError
from celery import Celery
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import pandas as pd
import io
import redis
import pika
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
import pybreaker

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
SERVICE_NAME = "reports"
SERVICE_VERSION = "4.1.0"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zeroque:zeroque@localhost:5432/zeroque_dev")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")

# Database setup
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Celery setup
celery_app = Celery(
    SERVICE_NAME,
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
    include=[f'{SERVICE_NAME}.tasks']
)

# Load Celery configuration
try:
    celery_app.config_from_object('celeryconfig')
except ImportError:
    logger.warning("Celery config not found, using defaults")

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# Prometheus metrics
report_requests_total = Counter('report_requests_total', 'Total report requests', ['report_type', 'status'])
report_request_duration = Histogram('report_request_duration_seconds', 'Report request duration', ['report_type'])
report_generation_duration = Histogram('report_generation_duration_seconds', 'Report generation duration', ['report_type'])
report_cache_hits = None
active_report_sessions = None

# Report types
class ReportType(str, Enum):
    SALES_ANALYTICS = "sales_analytics"
    INVENTORY_ANALYTICS = "inventory_analytics"
    CUSTOMER_ANALYTICS = "customer_analytics"
    OPERATIONAL_ANALYTICS = "operational_analytics"
    FINANCIAL_ANALYTICS = "financial_analytics"
    USAGE_ANALYTICS = "usage_analytics"
    PERFORMANCE_ANALYTICS = "performance_analytics"

# Phase 6: Dashboard types for Power BI integration
class DashboardType(str, Enum):
    OVERVIEW = "overview"
    SALES = "sales"
    INVENTORY = "inventory"
    CUSTOMER = "customer"
    OPERATIONAL = "operational"
    FINANCIAL = "financial"
    CUSTOM = "custom"

class ReportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    EXCEL = "xlsx"
    PDF = "pdf"

class ReportStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"

# ---- Database Models ----
class ReportJob(Base):
    __tablename__ = "report_jobs_new"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    report_type = Column(String, nullable=False)
    report_name = Column(String, nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default=ReportStatus.PENDING)
    file_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

class ReportCache(Base):
    __tablename__ = "report_cache_new"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    cache_key = Column(String, nullable=False, unique=True)
    report_type = Column(String, nullable=False)
    parameters_hash = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

# Phase 6: Dashboard Models for Power BI Integration
class Dashboard(Base):
    """Dashboard configuration for Power BI - Phase 6"""
    __tablename__ = "dashboards"

    dashboard_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    dashboard_type = Column(String(50), nullable=False)
    powerbi_workspace_id = Column(String(100), nullable=True)
    powerbi_report_id = Column(String(100), nullable=True)
    powerbi_dataset_id = Column(String(100), nullable=True)
    embed_config = Column(JSON, nullable=False, default=dict)
    data_sources = Column(JSON, nullable=False, default=list)  # List of service names
    refresh_schedule = Column(String(100), nullable=True)  # Cron format
    filters = Column(JSON, nullable=False, default=dict)
    is_public = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

class DashboardAccess(Base):
    """Dashboard access control - Phase 6"""
    __tablename__ = "dashboard_access"

    id = Column(String, primary_key=True)
    dashboard_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)  # null for public access
    role_id = Column(String, nullable=True)  # null for user-specific access
    permissions = Column(JSON, nullable=False, default=list)  # read, write, admin
    granted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

class DashboardDataRefresh(Base):
    """Dashboard data refresh tracking - Phase 6"""
    __tablename__ = "dashboard_data_refresh"

    id = Column(String, primary_key=True)
    dashboard_id = Column(String, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending, running, completed, failed
    last_refresh = Column(DateTime(timezone=True), nullable=True)
    next_refresh = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    refresh_duration_seconds = Column(Integer, nullable=True)
    records_processed = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=True)

# ---- Pydantic Models ----
class ReportRequest(BaseModel):
    tenant_id: str
    user_id: Optional[str] = None
    report_type: ReportType
    report_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    format: ReportFormat = ReportFormat.JSON
    cache_ttl_minutes: Optional[int] = 60

class ReportResponse(BaseModel):
    job_id: str
    status: ReportStatus
    message: str
    estimated_completion: Optional[datetime] = None

class ReportData(BaseModel):
    report_id: str
    report_type: ReportType
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    generated_at: datetime
    cache_hit: bool = False

class AnalyticsQuery(BaseModel):
    tenant_id: str
    start_date: datetime
    end_date: datetime
    filters: Dict[str, Any] = Field(default_factory=dict)
    group_by: Optional[List[str]] = None
    metrics: List[str] = Field(default_factory=list)

# Phase 6: Dashboard Models for Power BI Integration
class DashboardConfig(BaseModel):
    """Dashboard configuration for Power BI"""
    name: str = Field(..., description="Dashboard name")
    description: Optional[str] = Field(None, description="Dashboard description")
    dashboard_type: DashboardType = Field(..., description="Type of dashboard")
    powerbi_workspace_id: Optional[str] = Field(None, description="Power BI workspace ID")
    powerbi_report_id: Optional[str] = Field(None, description="Power BI report ID")
    powerbi_dataset_id: Optional[str] = Field(None, description="Power BI dataset ID")
    embed_config: Dict[str, Any] = Field(default_factory=dict, description="Power BI embed configuration")
    data_sources: List[str] = Field(default_factory=list, description="Data source service names")
    refresh_schedule: Optional[str] = Field(None, description="Data refresh schedule (cron format)")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Default dashboard filters")
    is_public: bool = Field(default=False, description="Whether dashboard is publicly accessible")

class DashboardResponse(BaseModel):
    """Dashboard response model"""
    dashboard_id: str
    name: str
    description: Optional[str]
    dashboard_type: DashboardType
    powerbi_workspace_id: Optional[str]
    powerbi_report_id: Optional[str]
    powerbi_dataset_id: Optional[str]
    embed_config: Dict[str, Any]
    data_sources: List[str]
    refresh_schedule: Optional[str]
    filters: Dict[str, Any]
    is_public: bool
    created_at: datetime
    updated_at: Optional[datetime]

class DashboardCreateRequest(BaseModel):
    """Dashboard creation request"""
    name: str = Field(..., description="Dashboard name")
    description: Optional[str] = Field(None, description="Dashboard description")
    dashboard_type: DashboardType = Field(..., description="Type of dashboard")
    powerbi_workspace_id: Optional[str] = Field(None, description="Power BI workspace ID")
    powerbi_report_id: Optional[str] = Field(None, description="Power BI report ID")
    powerbi_dataset_id: Optional[str] = Field(None, description="Power BI dataset ID")
    data_sources: List[str] = Field(default_factory=list, description="Data source service names")
    refresh_schedule: Optional[str] = Field(None, description="Data refresh schedule")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Default dashboard filters")
    is_public: bool = Field(default=False, description="Whether dashboard is publicly accessible")

class PowerBIEmbedRequest(BaseModel):
    """Power BI embed token request"""
    dashboard_id: str
    user_id: Optional[str] = None
    permissions: List[str] = Field(default_factory=list, description="User permissions for dashboard")

class PowerBIEmbedResponse(BaseModel):
    """Power BI embed response"""
    embed_token: str
    embed_url: str
    expiry: datetime
    permissions: List[str]

class DashboardDataRefresh(BaseModel):
    """Dashboard data refresh status"""
    dashboard_id: str
    status: str  # 'running', 'completed', 'failed'
    last_refresh: Optional[datetime]
    next_refresh: Optional[datetime]
    error_message: Optional[str]

# ---- Report Generators ----
class ReportGenerator:
    def __init__(self, db_session):
        self.db = db_session
        self.logger = logger.bind(service=SERVICE_NAME)
    
    async def generate_sales_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive sales analytics"""
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        tenant_id = params.get("tenant_id")
        group_by = params.get("group_by", ["day"])
        
        # Sales by period
        sales_query = text("""
            SELECT 
                DATE(o.created_at) as period,
                COUNT(*) as order_count,
                SUM(o.total_minor) as revenue_minor,
                AVG(o.total_minor) as avg_order_value,
                COUNT(DISTINCT o.customer_id) as unique_customers
            FROM orders_new o
            WHERE o.tenant_id = :tenant_id
                AND o.created_at BETWEEN :start_date AND :end_date
                AND o.status = 'completed'
            GROUP BY DATE(o.created_at)
            ORDER BY period
        """)
        
        sales_data = self.db.execute(sales_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()
        
        # Top products
        products_query = text("""
            SELECT 
                oi.offer_id,
                SUM(oi.quantity) as units_sold,
                SUM(oi.total_price_minor) as revenue_minor,
                COUNT(DISTINCT oi.order_id) as order_count
            FROM order_items_new oi
            JOIN orders_new o ON o.id = oi.order_id
            WHERE o.tenant_id = :tenant_id
                AND o.created_at BETWEEN :start_date AND :end_date
                AND o.status = 'completed'
            GROUP BY oi.offer_id
           ORDER BY revenue_minor DESC
            LIMIT 20
        """)
        
        products_data = self.db.execute(products_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()
        
        # Store performance
        stores_query = text("""
            SELECT 
                o.store_id,
                COUNT(*) as order_count,
                SUM(o.total_minor) as revenue_minor,
                AVG(o.total_minor) as avg_order_value
            FROM orders_new o
            WHERE o.tenant_id = :tenant_id
                AND o.created_at BETWEEN :start_date AND :end_date
                AND o.status = 'completed'
           GROUP BY o.store_id
           ORDER BY revenue_minor DESC
        """)
        
        stores_data = self.db.execute(stores_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()
        
        return {
            "sales_trends": [{"period": str(r[0]), "orders": r[1], "revenue": r[2], "avg_value": r[3], "customers": r[4]} for r in sales_data],
            "top_products": [{"offer_id": r[0], "units_sold": r[1], "revenue": r[2], "orders": r[3]} for r in products_data],
            "store_performance": [{"store_id": r[0], "orders": r[1], "revenue": r[2], "avg_value": r[3]} for r in stores_data],
            "summary": {
                "total_orders": sum(r[1] for r in sales_data),
                "total_revenue": sum(r[2] for r in sales_data),
                "avg_order_value": sum(r[2] for r in sales_data) / sum(r[1] for r in sales_data) if sales_data else 0,
                "unique_customers": len(set(r[4] for r in sales_data))
            }
        }
    
    async def generate_inventory_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate inventory analytics and insights"""
        tenant_id = params.get("tenant_id")
        store_id = params.get("store_id")
        
        # Current inventory levels
        inventory_query = text("""
            SELECT 
                i.sku,
                i.quantity_on_hand,
                i.quantity_reserved,
                i.quantity_available,
                i.last_updated
            FROM inventory_new i
            WHERE i.tenant_id = :tenant_id
        """)
        
        params_dict = {"tenant_id": tenant_id}
        if store_id:
            inventory_query = text("""
                SELECT 
                    i.sku,
                    i.quantity_on_hand,
                    i.quantity_reserved,
                    i.quantity_available,
                    i.last_updated
                FROM inventory_new i
                WHERE i.tenant_id = :tenant_id AND i.store_id = :store_id
            """)
            params_dict["store_id"] = store_id
        
        inventory_data = self.db.execute(inventory_query, params_dict).all()
        
        # Low stock items
        low_stock_query = text("""
            SELECT 
                i.sku,
                i.quantity_on_hand,
                i.quantity_available,
                i.store_id
            FROM inventory_new i
            WHERE i.tenant_id = :tenant_id
                AND i.quantity_available <= 10
            ORDER BY i.quantity_available ASC
        """)
        
        low_stock_data = self.db.execute(low_stock_query, {"tenant_id": tenant_id}).all()
        
        # Inventory movements
        movements_query = text("""
            SELECT 
                im.sku,
                im.movement_type,
                SUM(im.quantity_delta) as total_delta,
                COUNT(*) as movement_count
            FROM inventory_movements_new im
            WHERE im.tenant_id = :tenant_id
                AND im.created_at >= NOW() - INTERVAL '30 days'
            GROUP BY im.sku, im.movement_type
            ORDER BY total_delta DESC
        """)
        
        movements_data = self.db.execute(movements_query, {"tenant_id": tenant_id}).all()
        
        return {
            "current_inventory": [{"sku": r[0], "on_hand": r[1], "reserved": r[2], "available": r[3], "updated": r[4]} for r in inventory_data],
            "low_stock_alerts": [{"sku": r[0], "quantity": r[1], "available": r[2], "store_id": r[3]} for r in low_stock_data],
            "inventory_movements": [{"sku": r[0], "type": r[1], "delta": r[2], "count": r[3]} for r in movements_data],
            "summary": {
                "total_skus": len(inventory_data),
                "low_stock_items": len(low_stock_data),
                "total_value": sum(r[1] for r in inventory_data),  # Simplified calculation
                "movement_types": len(set(r[1] for r in movements_data))
            }
        }
    
    async def generate_customer_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate customer analytics and insights"""
        tenant_id = params.get("tenant_id")
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        
        # Customer acquisition
        acquisition_query = text("""
            SELECT 
                DATE(u.created_at) as acquisition_date,
                COUNT(*) as new_customers
            FROM users_new u
            WHERE u.tenant_id = :tenant_id
                AND u.created_at BETWEEN :start_date AND :end_date
            GROUP BY DATE(u.created_at)
            ORDER BY acquisition_date
        """)
        
        acquisition_data = self.db.execute(acquisition_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()
        
        # Customer lifetime value
        clv_query = text("""
            SELECT 
                o.customer_id,
                COUNT(*) as order_count,
                SUM(o.total_minor) as total_spent,
                AVG(o.total_minor) as avg_order_value,
                MIN(o.created_at) as first_order,
                MAX(o.created_at) as last_order
            FROM orders_new o
            WHERE o.tenant_id = :tenant_id
                AND o.status = 'completed'
            GROUP BY o.customer_id
            ORDER BY total_spent DESC
            LIMIT 100
        """)
        
        clv_data = self.db.execute(clv_query, {"tenant_id": tenant_id}).all()
        
        # Customer segments
        segments_query = text("""
            WITH customer_metrics AS (
                SELECT 
                    customer_id,
                    COUNT(*) as order_count,
                    SUM(total_minor) as total_spent,
                    AVG(total_minor) as avg_order_value
                FROM orders_new
                WHERE tenant_id = :tenant_id AND status = 'completed'
                GROUP BY customer_id
            )
            SELECT 
                CASE 
                    WHEN total_spent > 100000 THEN 'high_value'
                    WHEN total_spent > 50000 THEN 'medium_value'
                    ELSE 'low_value'
                END as segment,
                COUNT(*) as customer_count,
                AVG(total_spent) as avg_spent,
                AVG(order_count) as avg_orders
            FROM customer_metrics
            GROUP BY segment
        """)
        
        segments_data = self.db.execute(segments_query, {"tenant_id": tenant_id}).all()
        
        return {
            "customer_acquisition": [{"date": str(r[0]), "new_customers": r[1]} for r in acquisition_data],
            "top_customers": [{"customer_id": r[0], "orders": r[1], "total_spent": r[2], "avg_value": r[3], "first_order": r[4], "last_order": r[5]} for r in clv_data[:20]],
            "customer_segments": [{"segment": r[0], "count": r[1], "avg_spent": r[2], "avg_orders": r[3]} for r in segments_data],
            "summary": {
                "total_customers": len(clv_data),
                "new_customers": sum(r[1] for r in acquisition_data),
                "avg_customer_value": sum(r[2] for r in clv_data) / len(clv_data) if clv_data else 0,
                "top_spender": clv_data[0][2] if clv_data else 0
            }
        }
    
    async def generate_operational_analytics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate operational analytics and KPIs"""
        tenant_id = params.get("tenant_id")
        start_date = params.get("start_date")
        end_date = params.get("end_date")
        
        # Order processing times
        processing_query = text("""
            SELECT 
                DATE(created_at) as date,
                AVG(EXTRACT(EPOCH FROM (updated_at - created_at))/60) as avg_processing_minutes,
                COUNT(*) as order_count
            FROM orders_new
            WHERE tenant_id = :tenant_id
                AND created_at BETWEEN :start_date AND :end_date
                AND status = 'completed'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        
        processing_data = self.db.execute(processing_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()
        
        # System performance metrics
        performance_query = text("""
            SELECT 
                'orders_per_hour' as metric,
                COUNT(*) / GREATEST(EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at)))/3600, 1) as value
            FROM orders_new
            WHERE tenant_id = :tenant_id
                AND created_at BETWEEN :start_date AND :end_date
            UNION ALL
            SELECT 
                'completion_rate' as metric,
                COUNT(*) FILTER (WHERE status = 'completed') * 100.0 / COUNT(*) as value
            FROM orders_new
            WHERE tenant_id = :tenant_id
                AND created_at BETWEEN :start_date AND :end_date
        """)
        
        performance_data = self.db.execute(performance_query, {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date
        }).all()
        
        return {
            "processing_times": [{"date": str(r[0]), "avg_minutes": float(r[1]), "orders": r[2]} for r in processing_data],
            "performance_metrics": {r[0]: float(r[1]) for r in performance_data},
            "summary": {
                "avg_processing_time": sum(r[1] for r in processing_data) / len(processing_data) if processing_data else 0,
                "total_orders_processed": sum(r[2] for r in processing_data),
                "orders_per_hour": next((r[1] for r in performance_data if r[0] == 'orders_per_hour'), 0),
                "completion_rate": next((r[1] for r in performance_data if r[0] == 'completion_rate'), 0)
            }
        }

# ---- Application Setup ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info(f"Starting {SERVICE_NAME}", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    # Initialize database tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error("Failed to initialize database tables", error=str(e))
    
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
# CELERY TASKS
# =============================================================================

@celery_app.task(bind=True, max_retries=3)
def process_report_generation(self, job_id: str, report_type: str, parameters: Dict[str, Any]):
    """Process report generation asynchronously"""
    try:
        with SessionLocal() as db:
            # Get report job
            job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
            if not job:
                raise ValueError(f"Report job {job_id} not found")
            
            # Process report generation logic here
            logger.info(f"Processing report generation for job {job_id}, type {report_type}")
            
            # Update metrics
            report_requests_total.labels(report_type=report_type, status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process report generation for job {job_id}: {e}")
        report_requests_total.labels(report_type=report_type, status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def process_data_aggregation(self, tenant_id: str, aggregation_data: Dict[str, Any]):
    """Process data aggregation asynchronously"""
    try:
        with SessionLocal() as db:
            # Set RLS context (best-effort)
            try:
                db.execute(text("SET app.current_tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            except Exception:
                pass
            
            # Process data aggregation logic here
            logger.info(f"Processing data aggregation for tenant {tenant_id}")
            
            # Update metrics
            report_requests_total.labels(report_type="data_aggregation", status="success").inc()
            
    except Exception as e:
        logger.error(f"Failed to process data aggregation for tenant {tenant_id}: {e}")
        report_requests_total.labels(report_type="data_aggregation", status="failed").inc()
        raise self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=3)
def cleanup_old_reports(self):
    """Clean up old reports"""
    try:
        with SessionLocal() as db:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            
            # Clean up old report jobs
            job_result = db.execute(text("""
                DELETE FROM report_jobs_new 
                WHERE created_at < :cutoff_date AND status IN ('completed', 'failed')
            """), {"cutoff_date": cutoff_date})
            
            # Clean up old report data
            data_result = db.execute(text("""
                DELETE FROM report_data_new 
                WHERE created_at < :cutoff_date
            """), {"cutoff_date": cutoff_date})
            
            db.commit()
            
            logger.info(f"Cleaned up {job_result.rowcount} old report jobs and {data_result.rowcount} old report data")
            
    except Exception as e:
        logger.error(f"Failed to cleanup old reports: {e}")
        raise self.retry(exc=e, countdown=300)

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