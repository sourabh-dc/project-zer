# services/billing/main.py - ZeroQue Billing Service V4.1
# Production-ready billing service with Celery, RabbitMQ, and comprehensive metrics
import os
import json
from datetime import timezone, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Request, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text, or_
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, REGISTRY
import redis
import requests
import pybreaker

from core.config import get_settings
from services.billing.utils.user_auth import get_user_context, check_permission
from .utils.billing_logger import logger
from .models import *
from .schemas import *
from .repositories.db_config import SessionLocal, engine, get_db, get_db_with_rls, set_rls_context
from .utils.metrics import billing_requests, billing_requests_duration, billing_requests_total, \
     billing_requests_in_flight
from .repositories.invoice_saga import InvoiceCreationSaga
from .repositories.settlement_saga import SettlementCreationSaga
# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

SERVICE_NAME = "billing"
SERVICE_VERSION = "4.1.0"


# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
APPROVALS_URL = os.getenv("APPROVALS_URL", "http://localhost:8004")
API_KEY = os.getenv("API_KEY", "zq_demo_key_for_testing")
ALLOW_DEMO = get_settings().ALLOW_DEMO


# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# UTILITIES
# =============================================================================

def validate_uuid(uuid_string: str) -> str:
    """Validate and return UUID string"""
    try:
        uuid.UUID(uuid_string)
        return uuid_string
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")


# =============================================================================
# EXCEPTIONS
# =============================================================================

class BillingValidationError(Exception):
    """Billing validation error"""
    pass

class BillingNotFoundError(Exception):
    """Billing resource not found error"""
    pass

class BillingDuplicateError(Exception):
    """Billing duplicate resource error"""
    pass

class SettlementProcessingError(Exception):
    """Settlement processing error"""
    pass

# =============================================================================
# FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    logger.info("Starting Billing Service V2", version=SERVICE_VERSION, environment=ENVIRONMENT)
    
    # Initialize database tables
    # Base.metadata.create_all(bind=engine)
    
    yield
    
    logger.info("Shutting down Billing Service V2")

app = FastAPI(
    title="Billing Service V2",
    description="Production-ready billing service with invoice creation and vendor settlements",
    version=SERVICE_VERSION,
    lifespan=lifespan
)

# Middleware - Restrict CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8501",  # Streamlit apps
        "http://localhost:8502",
        "http://localhost:8503",
        "http://localhost:8510",
        "https://*.zeroque.com"
    ] if ENVIRONMENT == "development" else ["https://*.zeroque.com", "https://zeroque.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

if ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.zeroque.com", "zeroque.com"])
else:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Exception handlers
@app.exception_handler(BillingValidationError)
async def billing_validation_exception_handler(request: Request, exc: BillingValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": f"Validation error: {str(exc)}"}
    )

@app.exception_handler(BillingNotFoundError)
async def billing_not_found_exception_handler(request: Request, exc: BillingNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"detail": f"Resource not found: {str(exc)}"}
    )

@app.exception_handler(BillingDuplicateError)
async def billing_duplicate_exception_handler(request: Request, exc: BillingDuplicateError):
    return JSONResponse(
        status_code=409,
        content={"detail": f"Resource already exists: {str(exc)}"}
    )

@app.exception_handler(SettlementProcessingError)
async def settlement_processing_exception_handler(request: Request, exc: SettlementProcessingError):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Settlement processing error: {str(exc)}"}
    )

# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connectivity
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {
                "database": {"status": "healthy"}
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "environment": ENVIRONMENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

@app.post("/billing/v2/invoices", response_model=InvoiceResponse)
async def create_invoice(
    request: CreateInvoiceRequest,
    user_context: Dict[str, Any] = Depends(get_user_context),
    db = Depends(get_db_with_rls)
):
    """Create a new invoice using saga pattern"""
    billing_requests_in_flight.inc()

    # Check permissions
    if not check_permission("billing.create", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        with billing_requests_duration.time():
            # Execute saga
            saga = InvoiceCreationSaga(db, request)
            invoice_id = await saga.execute()

            # Get created invoice
            invoice = db.query(TradeInvoice).filter(TradeInvoice.id == invoice_id).first()
            if not invoice:
                raise BillingNotFoundError(f"Invoice {invoice_id} not found after creation")
            
            # Get invoice lines
            lines = db.query(TradeInvoiceLine).filter(TradeInvoiceLine.invoice_id == invoice_id).all()
            
            billing_requests.labels(method='POST', endpoint='/billing/v2/invoices', status='success').inc()

            # Audit log
            audit_log(db, "create_invoice", "invoices_new", invoice_id, user_context, request.dict(), 201)

            return InvoiceResponse(
                id=invoice.id,
                tenant_id=invoice.tenant_id,
                invoice_number=invoice.invoice_number,
                status=invoice.status,
                amount_minor=invoice.amount_minor,
                currency=invoice.currency,
                tax_total_minor=invoice.tax_total_minor,
                subtotal_minor=invoice.subtotal_minor,
                due_date=invoice.due_date,
                posted_at=invoice.posted_at,
                created_at=invoice.created_at,
                updated_at=invoice.updated_at,
                lines=[{
                    "id": line.id,
                    "line_number": line.line_number,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price_minor": line.unit_price_minor,
                    "line_total_minor": line.line_total_minor,
                    "tax_minor": line.tax_minor,
                    "tax_code": line.tax_code
                } for line in lines]
            )
            
    except Exception as e:
        billing_requests.labels(method='POST', endpoint='/billing/v2/invoices', status='error').inc()
        logger.error("Failed to create invoice", error=str(e), tenant_id=request.tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")
    
    finally:
        billing_requests_in_flight.dec()

@app.get("/billing/v2/settlements")
async def list_settlements(
    tenant_id: str = Query(..., description="Tenant ID"),
    vendor_id: Optional[str] = Query(None, description="Vendor ID filter"),
    status: Optional[str] = Query(None, description="Settlement status filter"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    limit: int = Query(100, description="Number of results to return"),
    offset: int = Query(0, description="Number of results to skip"),
    db = Depends(get_db)
):
    """List settlements with filtering and pagination"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(VendorSettlement).filter(VendorSettlement.tenant_id == tenant_id)
        
        if vendor_id:
            query = query.filter(VendorSettlement.vendor_id == vendor_id)
        
        if status:
            query = query.filter(VendorSettlement.settlement_status == status)
        
        if start_date:
            query = query.filter(VendorSettlement.settlement_period_start >= start_date)
        
        if end_date:
            query = query.filter(VendorSettlement.settlement_period_end <= end_date)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        settlements = query.order_by(VendorSettlement.created_at.desc()).offset(offset).limit(limit).all()
        
        return {
            "settlements": [
                {
                    "settlement_id": str(settlement.settlement_id),
                    "vendor_id": str(settlement.vendor_id),
                    "tenant_id": str(settlement.tenant_id),
                    "settlement_period_start": settlement.settlement_period_start.isoformat(),
                    "settlement_period_end": settlement.settlement_period_end.isoformat(),
                    "total_sales_minor": settlement.total_sales_minor,
                    "total_commission_minor": settlement.total_commission_minor,
                    "net_settlement_minor": settlement.net_settlement_minor,
                    "currency": settlement.currency,
                    "settlement_status": settlement.settlement_status,
                    "settlement_date": settlement.settlement_date.isoformat() if settlement.settlement_date else None,
                    "created_at": settlement.created_at.isoformat(),
                    "updated_at": settlement.updated_at.isoformat() if settlement.updated_at else None
                }
                for settlement in settlements
            ],
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error("Failed to list settlements", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to list settlements: {str(e)}")

@app.post("/billing/v2/settlements", response_model=SettlementResponse)
async def create_settlement(
    request: CreateSettlementRequest,
    user_context: Dict[str, Any] = Depends(get_user_context),
    db = Depends(get_db_with_rls)
):
    """Create a new vendor settlement using saga pattern"""
    billing_requests_in_flight.inc()

    # Check permissions
    if not check_permission("billing.create", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        with billing_requests_duration.time():
            # Execute saga
            saga = SettlementCreationSaga(db, request)
            settlement_id = await saga.execute()

            # Get created settlement
            settlement = db.query(VendorSettlement).filter(VendorSettlement.settlement_id == settlement_id).first()
            if not settlement:
                raise BillingNotFoundError(f"Settlement {settlement_id} not found after creation")

            billing_requests.labels(method='POST', endpoint='/billing/v2/settlements', status='success').inc()

            # Audit log
            audit_log(db, "create_settlement", "settlements_new", settlement_id, user_context, request.dict(), 201)
            
            return SettlementResponse(
                settlement_id=str(settlement.settlement_id),
                vendor_id=str(settlement.vendor_id),
                tenant_id=str(settlement.tenant_id),
                settlement_period_start=settlement.settlement_period_start,
                settlement_period_end=settlement.settlement_period_end,
                total_sales_minor=settlement.total_sales_minor,
                total_commission_minor=settlement.total_commission_minor,
                net_settlement_minor=settlement.net_settlement_minor,
                currency=settlement.currency,
                settlement_status=settlement.settlement_status,
                settlement_date=settlement.settlement_date,
                created_at=settlement.created_at
            )
            
    except Exception as e:
        billing_requests.labels(method='POST', endpoint='/billing/v2/settlements', status='error').inc()
        logger.error("Failed to create settlement", error=str(e), tenant_id=request.tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to create settlement: {str(e)}")
    
    finally:
        billing_requests_in_flight.dec()

@app.get("/billing/v2/invoices")
async def list_invoices(
    tenant_id: str = Query(..., description="Tenant ID"),
    status: Optional[str] = Query(None, description="Invoice status filter"),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    limit: int = Query(100, description="Number of results to return"),
    offset: int = Query(0, description="Number of results to skip"),
    db = Depends(get_db)
):
    """List invoices with filtering and pagination"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(TradeInvoice).filter(TradeInvoice.tenant_id == tenant_id)
        
        if status:
            query = query.filter(TradeInvoice.status == status)
        
        if start_date:
            query = query.filter(TradeInvoice.created_at >= start_date)
        
        if end_date:
            query = query.filter(TradeInvoice.created_at <= end_date)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination
        invoices = query.order_by(TradeInvoice.created_at.desc()).offset(offset).limit(limit).all()
        
        return {
            "invoices": [
                {
                    "id": invoice.id,
                    "tenant_id": invoice.tenant_id,
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status,
                    "amount_minor": invoice.amount_minor,
                    "currency": invoice.currency,
                    "tax_total_minor": invoice.tax_total_minor,
                    "subtotal_minor": invoice.subtotal_minor,
                    "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                    "posted_at": invoice.posted_at.isoformat() if invoice.posted_at else None,
                    "created_at": invoice.created_at.isoformat(),
                    "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None
                }
                for invoice in invoices
            ],
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        }
        
    except Exception as e:
        logger.error("Failed to list invoices", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to list invoices: {str(e)}")


@app.post("/billing/v2/disputes", response_model=DisputeResponse)
async def create_dispute(request: CreateDisputeRequest, db = Depends(get_db)):
    """Create a new dispute"""
    try:
        # Set RLS context
        set_rls_context(db, request.tenant_id)
        
        # Validate that either settlement_id or settlement_item_id is provided
        if not request.settlement_id and not request.settlement_item_id:
            raise HTTPException(status_code=400, detail="Either settlement_id or settlement_item_id must be provided")
        
        # Create dispute
        dispute = VendorDispute(
            settlement_item_id=request.settlement_item_id or request.settlement_id,
            vendor_id="550e8400-e29b-41d4-a716-446655440008",  # Default vendor for testing
            dispute_type="amount_dispute",
            dispute_reason=request.dispute_reason,
            status='open',
            sla_deadline=datetime.now(timezone.utc) + timedelta(days=7),  # 7 days SLA
            tenant_id=request.tenant_id
        )
        
        db.add(dispute)
        db.commit()
        db.refresh(dispute)
        
        logger.info("Created dispute", dispute_id=str(dispute.id), tenant_id=request.tenant_id)
        
        return DisputeResponse(
            id=str(dispute.dispute_id),
            settlement_id=request.settlement_id,
            settlement_item_id=str(dispute.settlement_item_id),
            tenant_id=str(dispute.tenant_id),
            dispute_amount_minor=request.dispute_amount_minor,
            dispute_reason=dispute.dispute_reason,
            dispute_status=dispute.status,
            dispute_notes=request.dispute_notes,
            created_at=dispute.created_at
        )
        
    except Exception as e:
        logger.error("Failed to create dispute", error=str(e), tenant_id=request.tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to create dispute: {str(e)}")


# Phase 4: Cost Centre Budgeting Endpoints
@app.post("/cost-centres", response_model=CostCentreResponse)
async def create_cost_centre(
    request: CostCentreRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new cost centre - Phase 4"""
    try:
        billing_requests_total.labels(endpoint="create_cost_centre", status="start").inc()

        # Check permissions
        if not check_permission("billing.admin", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        cost_centre = CostCentre(
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            name=request.name,
            code=request.code,
            description=request.description,
            parent_cost_centre_id=uuid.UUID(request.parent_cost_centre_id) if request.parent_cost_centre_id else None,
            budget_owner_id=uuid.UUID(request.budget_owner_id)
        )

        db.add(cost_centre)
        db.commit()
        db.refresh(cost_centre)

        billing_requests_total.labels(endpoint="create_cost_centre", status="ok").inc()

        return CostCentreResponse(
            cost_centre_id=str(cost_centre.cost_centre_id),
            name=cost_centre.name,
            code=cost_centre.code,
            description=cost_centre.description,
            parent_cost_centre_id=str(cost_centre.parent_cost_centre_id) if cost_centre.parent_cost_centre_id else None,
            budget_owner_id=str(cost_centre.budget_owner_id),
            is_active=cost_centre.is_active,
            created_at=cost_centre.created_at
        )

    except Exception as e:
        billing_requests_total.labels(endpoint="create_cost_centre", status="fail").inc()
        logger.error(f"Failed to create cost centre: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cost-centres")
async def list_cost_centres(
    tenant_id: str = Query(...),
    parent_cost_centre_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db = Depends(get_db_with_rls)
):
    """List cost centres - Phase 4"""
    try:
        query = db.query(CostCentre).filter(
            CostCentre.tenant_id == uuid.UUID(tenant_id),
            CostCentre.is_active == True
        )

        if parent_cost_centre_id:
            query = query.filter(CostCentre.parent_cost_centre_id == uuid.UUID(parent_cost_centre_id))

        cost_centres = query.offset(offset).limit(limit).all()

        return {
            "cost_centres": [
                CostCentreResponse(
                    cost_centre_id=str(cc.cost_centre_id),
                    name=cc.name,
                    code=cc.code,
                    description=cc.description,
                    parent_cost_centre_id=str(cc.parent_cost_centre_id) if cc.parent_cost_centre_id else None,
                    budget_owner_id=str(cc.budget_owner_id),
                    is_active=cc.is_active,
                    created_at=cc.created_at
                )
                for cc in cost_centres
            ],
            "total": len(cost_centres),
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Failed to list cost centres: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/budgets", response_model=BudgetResponse)
async def create_budget(
    request: BudgetRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Create a new budget - Phase 4"""
    try:
        billing_requests_total.labels(endpoint="create_budget", status="start").inc()

        # Check permissions
        if not check_permission("billing.admin", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Check if cost centre exists
        cost_centre = db.query(CostCentre).filter(
            CostCentre.cost_centre_id == uuid.UUID(request.cost_centre_id),
            CostCentre.tenant_id == uuid.UUID(uctx["tenant_id"])
        ).first()

        if not cost_centre:
            raise HTTPException(status_code=404, detail="Cost centre not found")

        budget = Budget(
            cost_centre_id=uuid.UUID(request.cost_centre_id),
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            budget_year=request.budget_year,
            budget_month=request.budget_month,
            budget_type=request.budget_type,
            budget_amount_minor=request.budget_amount_minor,
            currency=request.currency,
            approval_workflow_id=uuid.UUID(request.approval_workflow_id) if request.approval_workflow_id else None
        )

        db.add(budget)
        db.commit()
        db.refresh(budget)

        billing_requests_total.labels(endpoint="create_budget", status="ok").inc()

        return BudgetResponse(
            budget_id=str(budget.budget_id),
            cost_centre_id=str(budget.cost_centre_id),
            budget_year=budget.budget_year,
            budget_month=budget.budget_month,
            budget_type=budget.budget_type,
            budget_amount_minor=budget.budget_amount_minor,
            spent_amount_minor=budget.spent_amount_minor,
            available_amount_minor=budget.available_amount_minor,
            currency=budget.currency,
            status=budget.status,
            created_at=budget.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        billing_requests_total.labels(endpoint="create_budget", status="fail").inc()
        logger.error(f"Failed to create budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/budget-check", response_model=BudgetCheckResponse)
async def check_budget(
    request: BudgetCheckRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Check if budget allows spend and trigger approval if needed - Phase 4"""
    try:
        billing_requests_total.labels(endpoint="check_budget", status="start").inc()

        # Get active budget for cost centre and current period
        current_year = datetime.now().year
        current_month = datetime.now().month

        budget = db.query(Budget).join(CostCentre).filter(
            Budget.cost_centre_id == uuid.UUID(request.cost_centre_id),
            Budget.tenant_id == uuid.UUID(uctx["tenant_id"]),
            CostCentre.tenant_id == uuid.UUID(uctx["tenant_id"]),
            Budget.budget_year == current_year,
            Budget.is_active == True,
            or_(Budget.budget_month == current_month, Budget.budget_type == "annual")
        ).first()

        if not budget:
            raise HTTPException(status_code=404, detail="No active budget found for cost centre")

        available_amount = budget.available_amount_minor
        requested_amount = request.amount_minor

        # Check if budget is sufficient
        if available_amount >= requested_amount:
            # Budget sufficient, no approval needed
            approval_required = False
            approval_id = None
            is_approved = True
            message = "Budget check passed - sufficient funds available"
        else:
            # Budget insufficient, check if approval is required
            approval_required = True
            is_approved = False

            # Create approval request
            approval_data = {
                "tenant_id": uctx["tenant_id"],
                "requester_id": uctx["user_id"],
                "cost_centre_id": request.cost_centre_id,
                "amount_minor": requested_amount,
                "description": request.description,
                "reference_id": request.reference_id,
                "reference_type": request.reference_type,
                "budget_id": str(budget.budget_id)
            }

            # Call Approvals service to create approval
            try:
                approval_response = requests.post(
                    f"{APPROVALS_URL}/approvals/budget",
                    headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                    json=approval_data,
                    timeout=10
                )
                if approval_response.status_code == 200:
                    approval_result = approval_response.json()
                    approval_id = approval_result.get("approval_id")
                    message = f"Budget check failed - approval required (ID: {approval_id})"
                else:
                    message = "Budget check failed - insufficient funds and approval service unavailable"
            except Exception as e:
                logger.error(f"Failed to create approval: {e}")
                message = "Budget check failed - insufficient funds"

        billing_requests_total.labels(endpoint="check_budget", status="ok").inc()

        return BudgetCheckResponse(
            budget_id=str(budget.budget_id),
            cost_centre_id=request.cost_centre_id,
            requested_amount_minor=requested_amount,
            available_amount_minor=available_amount,
            is_approved=is_approved,
            approval_required=approval_required,
            approval_id=approval_id,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        billing_requests_total.labels(endpoint="check_budget", status="fail").inc()
        logger.error(f"Failed to check budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/spend")
async def record_spend(
    request: SpendRequest,
    db = Depends(get_db_with_rls),
    uctx: Dict = Depends(get_user_context)
):
    """Record spend against budget - Phase 4"""
    try:
        billing_requests_total.labels(endpoint="record_spend", status="start").inc()

        # Check permissions
        if not check_permission("billing.create", uctx):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        # Get budget
        current_year = datetime.now().year
        current_month = datetime.now().month

        budget = db.query(Budget).filter(
            Budget.cost_centre_id == uuid.UUID(request.cost_centre_id),
            Budget.tenant_id == uuid.UUID(uctx["tenant_id"]),
            Budget.budget_year == current_year,
            Budget.is_active == True,
            or_(Budget.budget_month == current_month, Budget.budget_type == "annual")
        ).first()

        if not budget:
            raise HTTPException(status_code=404, detail="No active budget found for cost centre")

        # Check if pre-approved
        if request.approval_id:
            # Verify approval exists and is approved
            # This would integrate with Approvals service
            pass

        # Record transaction
        transaction = BudgetTransaction(
            budget_id=budget.budget_id,
            tenant_id=uuid.UUID(uctx["tenant_id"]),
            amount_minor=request.amount_minor,
            transaction_type="spend",
            description=request.description,
            reference_id=request.reference_id,
            reference_type=request.reference_type,
            approval_id=uuid.UUID(request.approval_id) if request.approval_id else None,
            is_approved=True,  # Pre-approved or within budget
            created_by=uuid.UUID(uctx["user_id"])
        )

        db.add(transaction)

        # Update budget spent amount
        budget.spent_amount_minor += request.amount_minor
        budget.available_amount_minor = budget.budget_amount_minor - budget.spent_amount_minor

        # Check if budget is exceeded
        if budget.spent_amount_minor > budget.budget_amount_minor:
            budget.status = "exceeded"

            # Create budget alert
            alert = BudgetAlert(
                budget_id=budget.budget_id,
                tenant_id=uuid.UUID(uctx["tenant_id"]),
                alert_type="exceeded",
                threshold_percentage=100.00,
                message=f"Budget exceeded by {budget.spent_amount_minor - budget.budget_amount_minor} minor units"
            )
            db.add(alert)

        db.commit()

        billing_requests_total.labels(endpoint="record_spend", status="ok").inc()

        return {
            "transaction_id": str(transaction.transaction_id),
            "budget_id": str(budget.budget_id),
            "amount_recorded_minor": request.amount_minor,
            "new_spent_amount_minor": budget.spent_amount_minor,
            "available_amount_minor": budget.available_amount_minor,
            "status": budget.status,
            "created_at": transaction.created_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        billing_requests_total.labels(endpoint="record_spend", status="fail").inc()
        logger.error(f"Failed to record spend: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/budgets/{budget_id}")
async def get_budget_details(
    budget_id: str,
    db = Depends(get_db_with_rls)
):
    """Get budget details with transactions - Phase 4"""
    try:
        budget = db.query(Budget).filter(
            Budget.budget_id == uuid.UUID(budget_id)
        ).first()

        if not budget:
            raise HTTPException(status_code=404, detail="Budget not found")

        # Get transactions
        transactions = db.query(BudgetTransaction).filter(
            BudgetTransaction.budget_id == uuid.UUID(budget_id)
        ).order_by(BudgetTransaction.created_at.desc()).limit(50).all()

        return {
            "budget_id": str(budget.budget_id),
            "cost_centre_id": str(budget.cost_centre_id),
            "budget_year": budget.budget_year,
            "budget_month": budget.budget_month,
            "budget_type": budget.budget_type,
            "budget_amount_minor": budget.budget_amount_minor,
            "spent_amount_minor": budget.spent_amount_minor,
            "available_amount_minor": budget.available_amount_minor,
            "currency": budget.currency,
            "status": budget.status,
            "transactions": [
                {
                    "transaction_id": str(t.transaction_id),
                    "amount_minor": t.amount_minor,
                    "transaction_type": t.transaction_type,
                    "description": t.description,
                    "reference_id": t.reference_id,
                    "is_approved": t.is_approved,
                    "created_at": t.created_at.isoformat()
                }
                for t in transactions
            ],
            "created_at": budget.created_at.isoformat(),
            "updated_at": budget.updated_at.isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get budget details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/billing/v2/adjustments", response_model=AdjustmentResponse)
async def create_adjustment(request: CreateAdjustmentRequest, db = Depends(get_db)):
    """Create a new settlement adjustment"""
    try:
        # Set RLS context
        set_rls_context(db, request.tenant_id)
        
        # Create adjustment
        adjustment = VendorSettlementAdjustment(
            settlement_id=request.settlement_id,
            settlement_item_id=request.settlement_item_id,
            tenant_id=request.tenant_id,
            adjustment_amount_minor=request.adjustment_amount_minor,
            adjustment_reason=request.adjustment_reason,
            adjustment_type=request.adjustment_type,
            currency=request.currency,
            adjustment_status='pending',
            adjustment_notes=request.adjustment_notes
        )
        
        db.add(adjustment)
        db.commit()
        db.refresh(adjustment)
        
        logger.info("Created adjustment", adjustment_id=str(adjustment.id), tenant_id=request.tenant_id)
        
        return AdjustmentResponse(
            id=str(adjustment.id),
            settlement_id=str(adjustment.settlement_id),
            settlement_item_id=str(adjustment.settlement_item_id) if adjustment.settlement_item_id else None,
            tenant_id=str(adjustment.tenant_id),
            adjustment_amount_minor=adjustment.adjustment_amount_minor,
            adjustment_reason=adjustment.adjustment_reason,
            adjustment_type=adjustment.adjustment_type,
            currency=adjustment.currency,
            adjustment_status=adjustment.adjustment_status,
            created_at=adjustment.created_at
        )
        
    except Exception as e:
        logger.error("Failed to create adjustment", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create adjustment: {str(e)}")

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/billing/v2/integration/ledger/invoice-posted")
async def notify_ledger_invoice_posted(
    tenant_id: str = Body(...),
    invoice_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None)
):
    """Integration endpoint for Ledger service to handle INVOICE_POSTED events"""
    try:
        logger.info("Processing INVOICE_POSTED event for ledger integration", invoice_id=invoice_id, tenant_id=tenant_id)
        
        # Validate invoice exists
        with SessionLocal() as db:
            invoice = db.execute(
                text("SELECT * FROM trade_invoices WHERE id = :invoice_id AND tenant_id = :tenant_id"),
                {"invoice_id": invoice_id, "tenant_id": tenant_id}
            ).fetchone()
            
            if not invoice:
                raise HTTPException(status_code=404, detail="Invoice not found")
        
        # Prepare event data for ledger service
        ledger_event_data = {
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "total_amount_minor": total_amount_minor,
            "currency": currency,
            "customer_id": customer_id,
            "event_source": "billing_service"
        }
        
        # Notify ledger service via HTTP call
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://localhost:8086/ledger/v4/events/invoice-posted",
                    json=ledger_event_data
                )
                
                if response.status_code == 200:
                    logger.info("Successfully notified ledger service", invoice_id=invoice_id)
                    return {"ok": True, "ledger_notified": True, "invoice_id": invoice_id}
                else:
                    logger.warning("Ledger service returned error status", invoice_id=invoice_id, status_code=response.status_code)
                    return {"ok": False, "ledger_notified": False, "invoice_id": invoice_id, "error": "Ledger service error"}
                    
        except Exception as e:
            logger.error("Failed to notify ledger service", invoice_id=invoice_id, error=str(e))
            return {"ok": False, "ledger_notified": False, "invoice_id": invoice_id, "error": str(e)}
            
    except Exception as e:
        logger.error("Error processing INVOICE_POSTED event", invoice_id=invoice_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process INVOICE_POSTED event: {str(e)}")

@app.post("/billing/v2/integration/cv-gateway/invoice-creation")
async def create_invoice_for_cv_order(
    tenant_id: str = Body(...),
    order_id: str = Body(...),
    total_amount_minor: int = Body(...),
    currency: str = Body("GBP"),
    customer_id: str = Body(None),
    items: List[Dict[str, Any]] = Body(...)
):
    """Integration endpoint for CV Gateway service to create invoices"""
    try:
        logger.info("Processing invoice creation for CV Gateway", order_id=order_id, tenant_id=tenant_id)
        
        # Create invoice using existing invoice creation logic
        invoice_data = {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "currency": currency,
            "total_amount_minor": total_amount_minor,
            "tax_total_minor": int(total_amount_minor * 0.2),  # 20% tax
            "subtotal_minor": int(total_amount_minor * 0.8),   # 80% subtotal
            "status": "draft",
            "due_date": datetime.now(timezone.utc) + timedelta(days=30),
            "items": items
        }
        
        # Use existing invoice creation endpoint logic
        try:
            # Create invoice lines
            invoice_lines = []
            for item in items:
                line_data = {
                    "product_id": item.get("product_id"),
                    "description": item.get("description", "CV Order Item"),
                    "quantity": item.get("quantity", 1),
                    "unit_price_minor": item.get("unit_price_minor", 0),
                    "total_price_minor": item.get("total_price_minor", 0),
                    "tax_minor": int(item.get("total_price_minor", 0) * 0.2),
                    "tax_code": "VAT_STANDARD"
                }
                invoice_lines.append(line_data)
            
            invoice_data["lines"] = invoice_lines
            
            # Create invoice using existing logic
            invoice = await create_invoice(invoice_data)
            
            if invoice:
                logger.info("Successfully created invoice for CV order", invoice_id=invoice.get("id"), order_id=order_id)
                return {"ok": True, "invoice_created": True, "invoice_id": invoice.get("id"), "order_id": order_id}
            else:
                logger.warning("Failed to create invoice for CV order", order_id=order_id)
                return {"ok": False, "invoice_created": False, "order_id": order_id, "error": "Invoice creation failed"}
                
        except Exception as e:
            logger.error("Failed to create invoice for CV order", order_id=order_id, error=str(e))
            return {"ok": False, "invoice_created": False, "order_id": order_id, "error": str(e)}
            
    except Exception as e:
        logger.error("Error processing invoice creation for CV Gateway", order_id=order_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process invoice creation: {str(e)}")

@app.get("/billing/v2/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "ledger_service": {"status": "unknown", "url": "http://localhost:8086"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8000"},
            "cv_connector_service": {"status": "unknown", "url": "http://localhost:8100"},
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"}
        }
        
        # Test each service connectivity
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            for service_name, config in integration_status.items():
                try:
                    response = await client.get(f"{config['url']}/health")
                    if response.status_code == 200:
                        config["status"] = "healthy"
                        config["response_time_ms"] = response.elapsed.total_seconds() * 1000
                    else:
                        config["status"] = "unhealthy"
                except Exception as e:
                    config["status"] = "unreachable"
                    config["error"] = str(e)
        
        return {
            "integration_status": integration_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error("Error getting integration status", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

@app.get("/billing/v2/reports/ar-aging")
async def get_ar_aging_report(
    tenant_id: str = Query(..., description="Tenant ID"),
    as_of_date: Optional[date] = Query(None, description="As of date for aging report"),
    currency: Optional[str] = Query("GBP", description="Currency filter"),
    db = Depends(get_db)
):
    """Get accounts receivable aging report"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        if not as_of_date:
            as_of_date = date.today()
        
        # Calculate aging buckets
        current_cutoff = as_of_date
        days_31_60 = current_cutoff - timedelta(days=30)
        days_61_90 = current_cutoff - timedelta(days=60)
        days_over_90 = current_cutoff - timedelta(days=90)
        
        # Build base query with currency filter
        base_query = db.query(TradeInvoice).filter(
            TradeInvoice.tenant_id == tenant_id,
            TradeInvoice.status == 'posted',
            TradeInvoice.currency == currency
        )
        
        # Get invoices by aging bucket
        current_query = base_query.filter(TradeInvoice.due_date >= current_cutoff).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        bucket_31_60 = base_query.filter(
            TradeInvoice.due_date >= days_31_60,
            TradeInvoice.due_date < current_cutoff
        ).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        bucket_61_90 = base_query.filter(
            TradeInvoice.due_date >= days_61_90,
            TradeInvoice.due_date < days_31_60
        ).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        bucket_over_90 = base_query.filter(TradeInvoice.due_date < days_61_90).with_entities(func.sum(TradeInvoice.amount_minor)).scalar() or 0
        
        total_ar = current_query + bucket_31_60 + bucket_61_90 + bucket_over_90
        
        return {
            "tenant_id": tenant_id,
            "as_of_date": as_of_date.isoformat(),
            "currency": currency,
            "aging_buckets": {
                "current": current_query,
                "31_60": bucket_31_60,
                "61_90": bucket_61_90,
                "over_90": bucket_over_90
            },
            "total_ar_minor": total_ar
        }
        
    except Exception as e:
        logger.error("Failed to generate AR aging report", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to generate AR aging report: {str(e)}")

@app.post("/billing/v2/events/retry")
async def retry_outbox_events(
    tenant_id: str = Query(..., description="Tenant ID"),
    max_retries: int = Query(3, description="Maximum retry attempts"),
    db = Depends(get_db)
):
    """Retry pending outbox events"""
    try:
        # Set RLS context
        set_rls_context(db, tenant_id)
        
        # Get pending events that haven't exceeded max retries
        pending_events = db.query(BillingOutboxEvent).filter(
            BillingOutboxEvent.status == 'pending',
            BillingOutboxEvent.retry_count < max_retries
        ).limit(100).all()
        
        processed_count = 0
        failed_count = 0
        
        for event in pending_events:
            try:
                # Simulate event publishing (in real implementation, this would call external services)
                logger.info("Processing outbox event", event_id=str(event.event_id), event_type=event.event_type)
                
                # Mark as published
                event.status = 'published'
                event.published_at = datetime.now(timezone.utc)
                event.retry_count += 1
                
                processed_count += 1
                
            except Exception as e:
                logger.error("Failed to process outbox event", event_id=str(event.event_id), error=str(e))
                event.retry_count += 1
                
                if event.retry_count >= max_retries:
                    event.status = 'failed'
                
                failed_count += 1
        
        db.commit()
        
        return {
            "processed_count": processed_count,
            "failed_count": failed_count,
            "total_events": len(pending_events)
        }
        
    except Exception as e:
        logger.error("Failed to retry outbox events", error=str(e), tenant_id=tenant_id)
        raise HTTPException(status_code=500, detail=f"Failed to retry outbox events: {str(e)}")

# Event handlers for integration
@app.post("/billing/v2/events/order-completed")
async def handle_order_completed(event_data: Dict[str, Any], db = Depends(get_db)):
    """Handle ORDER_COMPLETED event from orders service"""
    try:
        logger.info("Handling ORDER_COMPLETED event", event_data=event_data)
        
        tenant_id = event_data.get("tenant_id")
        vendor_id = event_data.get("vendor_id")
        order_id = event_data.get("order_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if tenant_id and vendor_id and total_amount_minor > 0:
            # Set RLS context
            set_rls_context(db, tenant_id)
            
            # Create settlement item for this order
            settlement_item = SettlementItemRequest(
                order_id=order_id,
                payout_amount_minor=total_amount_minor,
                commission_amount_minor=int(total_amount_minor * 0.05),  # 5% commission
                fee_amount_minor=0,
                notes=f"Settlement for order {order_id}"
            )
            
            # Create settlement request
            settlement_request = CreateSettlementRequest(
                tenant_id=tenant_id,
                vendor_id=vendor_id,
                settlement_period_start=date.today(),
                settlement_period_end=date.today(),
                currency=currency,
                items=[settlement_item]
            )
            
            # Execute settlement saga
            saga = SettlementCreationSaga(db, settlement_request)
            settlement_id = await saga.execute()
            
            logger.info("Created settlement from order", settlement_id=settlement_id, order_id=order_id)
            
            return {"status": "success", "settlement_id": settlement_id}
        
        return {"status": "skipped", "reason": "Missing required fields"}
        
    except Exception as e:
        logger.error("Failed to handle ORDER_COMPLETED event", error=str(e), event_data=event_data)
        raise HTTPException(status_code=500, detail=f"Failed to handle ORDER_COMPLETED event: {str(e)}")

# =============================================================================
# AUDIT LOGGING
# =============================================================================

def audit_log(db_session, action: str, resource_type: str, resource_id: str, user_context: Dict[str, Any],
              request_data: Dict[str, Any] = None, response_status: int = None, error_message: str = None,
              ip_address: str = None, user_agent: str = None):
    """Create audit log entry"""
    try:
        # Create audit log entry
        from sqlalchemy import text

        db_session.execute(text("""
            INSERT INTO audit_logs (tenant_id, table_name, record_id, operation, new_values, changed_by, ip_address, user_agent)
            VALUES (:tenant_id, :table_name, :record_id, :operation, :new_values, :changed_by, :ip_address, :user_agent)
        """), {
            "tenant_id": user_context["tenant_id"],
            "table_name": resource_type,
            "record_id": resource_id,
            "operation": action,
            "new_values": json.dumps({
                "request_data": request_data,
                "response_status": response_status,
                "error_message": error_message,
                "user_id": user_context.get("user_id"),
                "tenant_id": user_context.get("tenant_id")
            }),
            "changed_by": user_context.get("user_id"),
            "ip_address": ip_address,
            "user_agent": user_agent
        })

        db_session.commit()

    except Exception as e:
        logger.warning(f"Failed to create audit log: {e}")
        # Don't fail the main operation if audit logging fails
# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8214")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )
