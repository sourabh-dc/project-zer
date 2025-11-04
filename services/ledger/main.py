# Ledger Service V2 - Enhanced V4.1 Architecture
# Double-entry accounting with sagas, events, and multi-tenant support
import os
import json
import hashlib
from datetime import  timezone, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Body, HTTPException, Query, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import redis
import httpx
import pybreaker

from core.config import get_settings
from services.ledger.repositories.daily_rollup_manager import DailyRollupManager
from services.ledger.repositories.database_ops import log_audit
from services.ledger.repositories.db_config import get_db_with_rls, set_rls_context, get_db, SessionLocal
from services.ledger.repositories.usage_monitoring import UsageMeteringManager
from services.ledger.services.fin_reporting_service import generate_pnl_summary, generate_cash_flow_summary, \
    generate_compliance_summary
from .utils.metrics import *
from .utils.ledger_logger import logger
from .services.celery_tasks import generate_daily_ledger_rollups, process_usage_metering
from .models import *
from .schemas import *
from .utils.user_auth import check_permission, get_user_context, check_rate_limit
from .repositories.ledger_entry_saga import LedgerEntrySaga
# =============================================================================
# CONFIGURATION
# =============================================================================

SERVICE_NAME = "ledger"
SERVICE_VERSION = "4.1.0"

# Configuration
DATABASE_URL = get_settings().DATABASE_URL
REDIS_URL = get_settings().REDIS_URL
RABBITMQ_URL = get_settings().RABBITMQ_URL
ENVIRONMENT = get_settings().ENVIRONMENT
ALLOW_DEMO = get_settings().ALLOW_DEMO
JWT_SECRET_KEY = get_settings().JWT_SECRET_KEY
JWT_ALGORITHM = get_settings().JWT_ALGORITHM
RATE_LIMIT_REQUESTS_PER_MINUTE = 60
EVENT_BUS_URL = os.getenv("EVENT_BUS_URL", "http://localhost:8085")

# Redis setup
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Circuit breaker for external service calls
service_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)

# =============================================================================
# IDEMPOTENCY UTILITIES
# =============================================================================

def generate_request_hash(request_data: dict) -> str:
    """Generate a hash of the request data for idempotency checking"""
    # Remove idempotency_key from hash calculation to avoid infinite loops
    hash_data = {k: v for k, v in request_data.items() if k != 'idempotency_key'}
    request_str = json.dumps(hash_data, sort_keys=True, default=str)
    return hashlib.sha256(request_str.encode()).hexdigest()

def get_or_create_idempotency_record(
    db: Session,
    idempotency_key: str,
    tenant_id: str,
    user_id: str,
    request_hash: str,
    request_data: dict
) -> tuple:
    """Get existing idempotency record or create new one"""
    # Check if record exists
    record = db.query(IdempotencyRecord).filter(
        IdempotencyRecord.idempotency_key == idempotency_key,
        IdempotencyRecord.tenant_id == tenant_id
    ).first()

    if record:
        # Check if request hash matches (same request)
        if record.request_hash == request_hash:
            # Same request, return cached response
            return record, True, record.response_data, record.status_code
        else:
            # Different request with same key - this is an error
            raise HTTPException(
                status_code=400,
                detail=f"Idempotency key '{idempotency_key}' already used for different request"
            )

    # Create new record
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)  # 24 hour expiry
    new_record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        user_id=user_id,
        request_hash=request_hash,
        response_data={},  # Will be updated after successful operation
        status_code=0,     # Will be updated after successful operation
        expires_at=expires_at
    )
    db.add(new_record)
    db.flush()  # Get the ID without committing

    return new_record, False, None, None

def update_idempotency_record(
    db: Session,
    record: IdempotencyRecord,
    response_data: dict,
    status_code: int
):
    """Update idempotency record with response data"""
    record.response_data = response_data
    record.status_code = status_code
    db.commit()

def cleanup_expired_idempotency_records(db: Session):
    """Clean up expired idempotency records"""
    try:
        expired_count = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.expires_at < datetime.now(timezone.utc)
        ).delete(synchronize_session=False)
        if expired_count > 0:
            db.commit()
            ledger_idempotency_cleanup_total.inc(expired_count)
            logger.info(f"Cleaned up {expired_count} expired idempotency records")
        return expired_count
    except Exception as e:
        logger.error(f"Failed to cleanup expired idempotency records: {e}")
        db.rollback()
        return 0

async def check_idempotency_and_execute(
    db: Session,
    idempotency_key: str,
    tenant_id: str,
    user_id: str,
    request_data: dict,
    operation_func,
    operation_name: str
) -> dict:
    """Check idempotency and execute operation with caching"""
    if not idempotency_key:
        # No idempotency key provided, execute normally
        return await operation_func()

    # Generate request hash
    request_hash = generate_request_hash(request_data)

    try:
        # Check or create idempotency record
        record, is_existing, cached_response, cached_status = get_or_create_idempotency_record(
            db, idempotency_key, tenant_id, user_id, request_hash, request_data
        )

        if is_existing:
            # Return cached response
            ledger_idempotency_requests_total.labels(
                operation=operation_name, status="cached"
            ).inc()
            ledger_idempotency_cache_hits.labels(operation=operation_name).inc()
            logger.info(f"Returning cached response for idempotency key: {idempotency_key}")
            return cached_response

        # Execute the operation
        try:
            result = await operation_func()

            # Update the idempotency record with successful result
            update_idempotency_record(db, record, result, 200)

            ledger_idempotency_requests_total.labels(
                operation=operation_name, status="new"
            ).inc()

            return result

        except Exception as e:
            # Update the idempotency record with error result
            error_response = {"error": str(e), "detail": "Operation failed"}
            update_idempotency_record(db, record, error_response, 500)

            ledger_idempotency_requests_total.labels(
                operation=operation_name, status="error"
            ).inc()

            raise e

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Idempotency check failed: {e}")
        # Fallback: execute operation without idempotency
        return await operation_func()

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown
    engine.dispose()

app = FastAPI(
    title="ZeroQue Ledger Service V2",
    version=SERVICE_VERSION
    # lifespan=lifespan  # Temporarily disabled for debugging
)

# Production Middleware - Restrict CORS origins
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

# =============================================================================
# HEALTH AND MONITORING ENDPOINTS
# =============================================================================

@app.get("/")
def root():
    return {"service": SERVICE_NAME, "version": SERVICE_VERSION}

@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}

@app.get("/readiness")
def readiness():
    return {"service": SERVICE_NAME, "db": True, "redis": True}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# =============================================================================
# V4 ENDPOINTS
# =============================================================================

@app.post("/ledger/v4/entries", response_model=dict)
async def create_ledger_entry(
    request: LedgerEntryRequest,
    user_context: Dict[str, Any] = Depends(get_user_context),
    db = Depends(get_db_with_rls)
):
    """Create ledger entry with saga pattern and idempotency support"""
    # Check rate limit
    if not await check_rate_limit(user_context["user_id"]):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Check permissions
    if not check_permission("ledger.create", user_context):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Update metrics
    ledger_requests_total.labels(
        method="POST", endpoint="/ledger/v4/entries", status="started"
    ).inc()

    start_time = datetime.now()

    async def execute_ledger_creation():
        """Inner function to execute the ledger creation logic"""
        set_rls_context(db, request.tenant_id)

        # Execute saga
        saga = LedgerEntrySaga(db, request)
        result = await saga.execute()

        # Update metrics
        duration = (datetime.now() - start_time).total_seconds()
        ledger_request_duration.labels(
            method="POST", endpoint="/ledger/v4/entries"
        ).observe(duration)

        ledger_saga_duration.labels(saga_type="create_entry").observe(duration)

        ledger_entries_created_total.labels(
            entry_type=request.entry_type,
            account=request.account,
            currency=request.currency
        ).inc()

        return result

    try:
        # Use idempotency wrapper
        result = await check_idempotency_and_execute(
            db=db,
            idempotency_key=request.idempotency_key,
            tenant_id=request.tenant_id,
            user_id=user_context.get("user_id"),
            request_data=request.dict(),
            operation_func=execute_ledger_creation,
            operation_name="entries"
        )

        return result

    except HTTPException:
        # Re-raise HTTP exceptions (like idempotency conflicts)
        raise
    except Exception as e:
        # Update metrics for errors
        duration = (datetime.now() - start_time).total_seconds()
        ledger_request_duration.labels(
            method="POST", endpoint="/ledger/v4/entries"
        ).observe(duration)

        ledger_saga_failures.labels(saga_type="create_entry", step="execute").inc()

        raise HTTPException(status_code=500, detail=f"Failed to create ledger entry: {str(e)}")

@app.get("/ledger/v4/entries")
async def list_ledger_entries(
    tenant_id: str = Query(..., description="Tenant ID"),
    account: Optional[str] = Query(None, description="Filter by account"),
    cost_centre_id: Optional[str] = Query(None, description="Filter by cost centre"),
    vendor_id: Optional[str] = Query(None, description="Filter by vendor"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    reference_type: Optional[str] = Query(None, description="Filter by reference type"),
    limit: int = Query(50, description="Limit results", le=1000),
    offset: int = Query(0, description="Offset for pagination", ge=0),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """List ledger entries with filtering"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(LedgerEntryNew).filter(LedgerEntryNew.tenant_id == tenant_id)
        
        if account:
            query = query.filter(LedgerEntryNew.account == account)
        if cost_centre_id:
            query = query.filter(LedgerEntryNew.cost_centre_id == cost_centre_id)
        if vendor_id:
            query = query.filter(LedgerEntryNew.vendor_id == vendor_id)
        if currency:
            query = query.filter(LedgerEntryNew.currency == currency)
        if reference_type:
            query = query.filter(LedgerEntryNew.reference_type == reference_type)
        
        # Get total count
        total_count = query.count()
        
        # Apply pagination and ordering
        entries = query.order_by(LedgerEntryNew.created_at.desc()).offset(offset).limit(limit).all()
        
        # Convert to response format
        items = [
            LedgerEntryResponse(
                id=str(entry.id),
                tenant_id=str(entry.tenant_id),
                vendor_id=str(entry.vendor_id) if entry.vendor_id else None,
                account=entry.account,
                entry_type=entry.entry_type,
                amount_minor=entry.amount_minor,
                currency=entry.currency,
                cost_centre_id=str(entry.cost_centre_id) if entry.cost_centre_id else None,
                site_id=str(entry.site_id) if entry.site_id else None,
                store_id=str(entry.store_id) if entry.store_id else None,
                reference_type=entry.reference_type,
                reference_id=entry.reference_id,
                description=entry.description,
                metadata=entry.metadata,
                created_at=entry.created_at,
                updated_at=entry.updated_at
            )
            for entry in entries
        ]
        
        return {
            "items": items,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total_count
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list ledger entries: {str(e)}")

@app.get("/ledger/v4/balances")
async def get_account_balances(
    tenant_id: str = Query(..., description="Tenant ID"),
    account: Optional[str] = Query(None, description="Filter by account"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    cost_centre_id: Optional[str] = Query(None, description="Filter by cost centre"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get account balances"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, tenant_id)
        
        # Build query
        query = db.query(AccountBalanceNew).filter(AccountBalanceNew.tenant_id == tenant_id)
        
        if account:
            query = query.filter(AccountBalanceNew.account == account)
        if currency:
            query = query.filter(AccountBalanceNew.currency == currency)
        
        balances = query.all()
        
        # Convert to response format
        items = [
            AccountBalanceResponse(
                account=balance.account,
                currency=balance.currency,
                balance_minor=balance.balance_minor,
                last_updated=balance.last_updated
            )
            for balance in balances
        ]
        
        return {"balances": items}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get account balances: {str(e)}")

@app.post("/ledger/v4/adjustments")
async def create_ledger_adjustment(
    request: LedgerAdjustmentRequest,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Create ledger adjustment for disputes/reconciliation with idempotency support"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async def execute_adjustment():
        """Inner function to execute the adjustment logic"""
        # Get original entry
        original_entry = db.query(LedgerEntryNew).filter(
            LedgerEntryNew.id == request.entry_id
        ).first()

        if not original_entry:
            raise HTTPException(status_code=404, detail="Entry not found")

        set_rls_context(db, original_entry.tenant_id)

        # Create adjustment entry
        adjustment_request = LedgerEntryRequest(
            tenant_id=original_entry.tenant_id,
            vendor_id=original_entry.vendor_id,
            account=original_entry.account,
            entry_type="credit" if original_entry.entry_type == "debit" else "debit",
            amount_minor=request.adjustment_amount_minor,
            currency=original_entry.currency,
            cost_centre_id=original_entry.cost_centre_id,
            site_id=original_entry.site_id,
            store_id=original_entry.store_id,
            reference_type=request.reference_type or "adjustment",
            reference_id=request.reference_id or f"adj_{request.entry_id}",
            description=f"Adjustment: {request.reason}",
            metadata={
                "original_entry_id": request.entry_id,
                "adjustment_reason": request.reason,
                "adjusted_by": user_context.get("user_id")
            }
        )

        # Execute saga
        saga = LedgerEntrySaga(db, adjustment_request)
        result = await saga.execute()

        # Log audit
        await log_audit(
            db,
            "create_ledger_adjustment",
            "ledger_entry",
            resource_id=str(result["entry_id"]),
            details={
                "original_entry_id": request.entry_id,
                "adjustment_amount_minor": request.adjustment_amount_minor,
                "reason": request.reason
            },
            user_id=user_context.get("user_id"),
            tenant_id=original_entry.tenant_id
        )

        return {
            "ok": True,
            "adjustment_entry_id": result["entry_id"],
            "original_entry_id": request.entry_id,
            "adjustment_amount_minor": request.adjustment_amount_minor
        }

    try:
        # Use idempotency wrapper
        result = await check_idempotency_and_execute(
            db=db,
            idempotency_key=request.idempotency_key,
            tenant_id=user_context.get("tenant_id"),
            user_id=user_context.get("user_id"),
            request_data=request.dict(),
            operation_func=execute_adjustment,
            operation_name="adjustments"
        )

        return result

    except HTTPException:
        # Re-raise HTTP exceptions (like idempotency conflicts)
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create adjustment: {str(e)}")

@app.get("/ledger/v4/reports")
async def get_ledger_report(
    request: LedgerReportRequest = Depends(),
    vendor_id: Optional[str] = Query(None, description="Filter by vendor"),
    include_vendor_splits: bool = Query(False, description="Include vendor revenue splits"),
    include_currency_conversion: bool = Query(False, description="Include currency conversion"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get ledger report with analytics (blueprint-inspired) including vendor splits"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        set_rls_context(db, request.tenant_id)
        
        # Build query for entries
        query = db.query(LedgerEntryNew).filter(LedgerEntryNew.tenant_id == request.tenant_id)
        
        if request.start_date:
            query = query.filter(LedgerEntryNew.created_at >= request.start_date)
        if request.end_date:
            query = query.filter(LedgerEntryNew.created_at <= request.end_date)
        if request.account:
            query = query.filter(LedgerEntryNew.account == request.account)
        if request.cost_centre_id:
            query = query.filter(LedgerEntryNew.cost_centre_id == request.cost_centre_id)
        if request.currency:
            query = query.filter(LedgerEntryNew.currency == request.currency)
        if vendor_id:
            query = query.filter(LedgerEntryNew.vendor_id == vendor_id)
        
        entries = query.all()
        
        # Aggregate by account and currency
        account_summary = {}
        vendor_summary = {} if include_vendor_splits else None
        
        for entry in entries:
            # Account-level aggregation
            key = f"{entry.account}_{entry.currency}"
            if key not in account_summary:
                account_summary[key] = {
                    "account": entry.account,
                    "currency": entry.currency,
                    "total_debits_minor": 0,
                    "total_credits_minor": 0,
                    "net_minor": 0,
                    "entry_count": 0
                }
            
            summary = account_summary[key]
            summary["entry_count"] += 1
            
            if entry.entry_type == "debit":
                summary["total_debits_minor"] += entry.amount_minor
                summary["net_minor"] += entry.amount_minor
            else:
                summary["total_credits_minor"] += entry.amount_minor
                summary["net_minor"] -= entry.amount_minor
            
            # Vendor-level aggregation for revenue splits
            if include_vendor_splits and entry.vendor_id:
                vendor_key = f"{entry.vendor_id}_{entry.currency}"
                if vendor_key not in vendor_summary:
                    vendor_summary[vendor_key] = {
                        "vendor_id": str(entry.vendor_id),
                        "currency": entry.currency,
                        "total_revenue_minor": 0,
                        "total_expenses_minor": 0,
                        "net_revenue_minor": 0,
                        "entry_count": 0
                    }
                
                vendor_summ = vendor_summary[vendor_key]
                vendor_summ["entry_count"] += 1
                
                if entry.entry_type == "debit" and entry.account in ["CostCentreSpend", "VendorRevenue"]:
                    vendor_summ["total_revenue_minor"] += entry.amount_minor
                    vendor_summ["net_revenue_minor"] += entry.amount_minor
                elif entry.entry_type == "credit" and entry.account in ["VendorExpenses", "MarketplaceFees"]:
                    vendor_summ["total_expenses_minor"] += entry.amount_minor
                    vendor_summ["net_revenue_minor"] -= entry.amount_minor
        
        # Currency conversion (simplified - in production would use exchange_rates table)
        if include_currency_conversion:
            for key, summary in account_summary.items():
                if summary["currency"] != "GBP":
                    # Simplified conversion (in production, use actual exchange rates)
                    conversion_rate = 1.0
                    if summary["currency"] == "USD":
                        conversion_rate = 0.8  # Example: 1 USD = 0.8 GBP
                    elif summary["currency"] == "EUR":
                        conversion_rate = 0.85  # Example: 1 EUR = 0.85 GBP
                    
                    summary["gbp_equivalent"] = {
                        "total_debits_minor": int(summary["total_debits_minor"] * conversion_rate),
                        "total_credits_minor": int(summary["total_credits_minor"] * conversion_rate),
                        "net_minor": int(summary["net_minor"] * conversion_rate),
                        "conversion_rate": conversion_rate
                    }
        
        result = {
            "tenant_id": request.tenant_id,
            "period": {
                "start_date": request.start_date.isoformat() if request.start_date else None,
                "end_date": request.end_date.isoformat() if request.end_date else None
            },
            "filters": {
                "account": request.account,
                "cost_centre_id": request.cost_centre_id,
                "currency": request.currency,
                "vendor_id": vendor_id
            },
            "summary": list(account_summary.values()),
            "total_entries": len(entries),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add vendor splits if requested
        if include_vendor_splits and vendor_summary:
            result["vendor_splits"] = list(vendor_summary.values())
        
        # Add currency conversion info if requested
        if include_currency_conversion:
            result["currency_conversion"] = {
                "base_currency": "GBP",
                "note": "Conversion rates are simplified for demo purposes"
            }
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")

# =============================================================================
# EVENT HANDLERS
# =============================================================================

@app.post("/ledger/v4/events/order-completed")
async def handle_order_completed(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle ORDER_COMPLETED event from Orders/CV services"""
    try:
        tenant_id = event_data.get("tenant_id")
        order_id = event_data.get("order_id")
        amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not tenant_id or not order_id or amount_minor <= 0:
            return {"ok": False, "message": "Invalid event data"}
        
        # Create ledger entry for order completion
        ledger_request = LedgerEntryRequest(
            tenant_id=tenant_id,
            account="CostCentreSpend",
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="order",
            reference_id=order_id,
            description=f"Order completion: {order_id}",
            metadata={
                "order_data": event_data,
                "event_source": "order_completed"
            }
        )

        saga = LedgerEntrySaga(db, ledger_request)
        result = await saga.execute()

        # Audit log
        await log_audit(
            db,
            "create_ledger_entry",
            "ledger_entry",
            result["entry_id"],
            details={
                "tenant_id": tenant_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "event_source": "order_completed"
            },
            tenant_id=tenant_id
        )

        return {"ok": True, "ledger_entry_id": result["entry_id"]}

    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/ledger/v4/events/invoice-posted")
async def handle_invoice_posted(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        tenant_id = event_data.get("tenant_id")
        invoice_id = event_data.get("invoice_id")
        amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not tenant_id or not invoice_id or amount_minor <= 0:
            return {"ok": False, "message": "Invalid event data"}
        
        # Create ledger entry for invoice posting
        ledger_request = LedgerEntryRequest(
            tenant_id=tenant_id,
            account="AccountsReceivable",
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="invoice",
            reference_id=invoice_id,
            description=f"Invoice posted: {invoice_id}",
            metadata={
                "invoice_data": event_data,
                "event_source": "invoice_posted"
            }
        )
        
        saga = LedgerEntrySaga(db, ledger_request)
        result = await saga.execute()
        
        return {"ok": True, "ledger_entry_id": result["entry_id"]}
        
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/ledger/v4/events/approval-resolved")
async def handle_approval_resolved(
    event_data: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Handle APPROVAL_RESOLVED event from Approvals service"""
    try:
        tenant_id = event_data.get("tenant_id")
        request_id = event_data.get("request_id")
        amount_minor = event_data.get("amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        approved = event_data.get("approved", False)
        
        if not tenant_id or not request_id:
            return {"ok": False, "message": "Invalid event data"}
        
        if approved and amount_minor > 0:
            # Create ledger entry for approved budget allocation
            ledger_request = LedgerEntryRequest(
                tenant_id=tenant_id,
                account="BudgetAllocation",
                entry_type="credit",
                amount_minor=amount_minor,
                currency=currency,
                reference_type="approval",
                reference_id=request_id,
                description=f"Budget allocated: {request_id}",
                metadata={
                    "approval_data": event_data,
                    "event_source": "approval_resolved"
                }
            )
            
            saga = LedgerEntrySaga(db, ledger_request)
            result = await saga.execute()
            
            return {"ok": True, "ledger_entry_id": result["entry_id"]}
        else:
            return {"ok": True, "message": "No ledger entry needed for denied approval"}
        
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/ledger/v4/events/retry")
async def retry_failed_events(
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Retry failed event publishing"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Get pending events that haven't exceeded max retries
        pending_events = db.query(OutboxEvent).filter(
            OutboxEvent.status == 'pending',
            OutboxEvent.retry_count < OutboxEvent.max_retries
        ).all()
        
        retried_count = 0
        failed_count = 0
        
        for event in pending_events:
            try:
                # Simulate event publishing (in production, this would call actual event bus)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(
                        f"{EVENT_BUS_URL}/events",
                        json={
                            "event_type": event.event_type,
                            "event_data": event.event_data,
                            "tenant_id": str(event.tenant_id) if event.tenant_id else None
                        }
                    )
                    
                    if response.status_code == 200:
                        event.status = 'published'
                        event.updated_at = datetime.now(timezone.utc)
                        retried_count += 1
                    else:
                        event.retry_count += 1
                        event.updated_at = datetime.now(timezone.utc)
                        if event.retry_count >= event.max_retries:
                            event.status = 'failed'
                        failed_count += 1
                        
            except Exception as e:
                event.retry_count += 1
                event.updated_at = datetime.now(timezone.utc)
                if event.retry_count >= event.max_retries:
                    event.status = 'failed'
                failed_count += 1
        
        db.commit()
        
        return {
            "ok": True,
            "retried_events": retried_count,
            "failed_events": failed_count,
            "total_processed": len(pending_events)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to retry events: {str(e)}")

@app.get("/ledger/v4/events/status")
async def get_event_status(
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get event publishing status"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Get event statistics
        total_events = db.query(OutboxEvent).count()
        pending_events = db.query(OutboxEvent).filter(OutboxEvent.status == 'pending').count()
        published_events = db.query(OutboxEvent).filter(OutboxEvent.status == 'published').count()
        failed_events = db.query(OutboxEvent).filter(OutboxEvent.status == 'failed').count()
        
        success_rate = (published_events / total_events * 100) if total_events > 0 else 0
        
        # Get last event time
        last_event = db.query(OutboxEvent).order_by(OutboxEvent.created_at.desc()).first()
        last_event_time = last_event.created_at.isoformat() if last_event else None
        
        return {
            "total_events": total_events,
            "pending_events": pending_events,
            "published_events": published_events,
            "failed_events": failed_events,
            "success_rate": round(success_rate, 2),
            "last_event_time": last_event_time
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event status: {str(e)}")

# =============================================================================
# LEGACY ENDPOINTS (DEPRECATED)
# =============================================================================

@app.get("/ledger")
def list_ledger_legacy(
    tenant_id: str = Query(...),
    account: Optional[str] = Query(None),
    cost_centre_id: Optional[str] = Query(None),
    cursor: Optional[int] = Query(None),
    limit: int = Query(100)
):
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/ledger/v4/entries",
        "message": "This endpoint is deprecated. Please use /ledger/v4/entries"
    }

@app.get("/ledger/balance")
def balance_legacy(
    tenant_id: str = Query(...),
    cost_centre_id: Optional[str] = Query(None)
):
    """Legacy endpoint - deprecated"""
    return {
        "deprecated": True,
        "migrate_to": "/ledger/v4/balances",
        "message": "This endpoint is deprecated. Please use /ledger/v4/balances"
    }

# =============================================================================
# INTEGRATION ENDPOINTS
# =============================================================================

@app.post("/ledger/v4/integration/orders/order-completed")
async def handle_order_completed_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle ORDER_COMPLETED event from Orders service"""
    try:
        logger.info(f"Received ORDER_COMPLETED event: {event_data}")
        
        order_id = event_data.get("order_id")
        tenant_id = event_data.get("tenant_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not order_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing order_id or tenant_id")
        
        # Create ledger entries for the completed order
        try:
            # Create debit entry (cost center spend)
            debit_entry = {
                "tenant_id": tenant_id,
                "account": "CostCentreSpend",
                "entry_type": "debit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "order",
                "reference_id": order_id,
                "description": f"Order completed: {order_id}"
            }
            
            # Create credit entry (cash/accounts payable)
            credit_entry = {
                "tenant_id": tenant_id,
                "account": "Cash",
                "entry_type": "credit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "order",
                "reference_id": order_id,
                "description": f"Payment received for order: {order_id}"
            }
            
            # Create entries using saga
            # from .sagas import LedgerEntrySaga
            
            saga = LedgerEntrySaga()
            result = await saga.create_double_entry(
                tenant_id=tenant_id,
                debit_entry=debit_entry,
                credit_entry=credit_entry
            )
            
            logger.info(f"Successfully created ledger entries for order: {result}")
            return {"ok": True, "ledger_entries_created": True, "result": result}
            
        except Exception as e:
            logger.error(f"Failed to create ledger entries: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling ORDER_COMPLETED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.post("/ledger/v4/integration/approvals/approval-resolved")
async def handle_approval_resolved_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle APPROVAL_RESOLVED event from Approvals service"""
    try:
        logger.info(f"Received APPROVAL_RESOLVED event: {event_data}")
        
        approval_id = event_data.get("approval_id")
        tenant_id = event_data.get("tenant_id")
        amount_minor = event_data.get("amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        status = event_data.get("status")
        
        if not approval_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing approval_id or tenant_id")
        
        # Create ledger entries based on approval status
        try:
            if status == "approved":
                # Create debit entry (approved spend)
                debit_entry = {
                    "tenant_id": tenant_id,
                    "account": "ApprovedSpend",
                    "entry_type": "debit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Approval granted: {approval_id}"
                }
                
                # Create credit entry (budget allocated)
                credit_entry = {
                    "tenant_id": tenant_id,
                    "account": "BudgetAllocated",
                    "entry_type": "credit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Budget allocated for approval: {approval_id}"
                }
            else:
                # For denied approvals, create reversal entries
                debit_entry = {
                    "tenant_id": tenant_id,
                    "account": "BudgetAllocated",
                    "entry_type": "debit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Approval denied - budget reversal: {approval_id}"
                }
                
                credit_entry = {
                    "tenant_id": tenant_id,
                    "account": "ApprovedSpend",
                    "entry_type": "credit",
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference_type": "approval",
                    "reference_id": approval_id,
                    "description": f"Approval denied - spend reversal: {approval_id}"
                }
            
            saga = LedgerEntrySaga()
            result = await saga.create_double_entry(
                tenant_id=tenant_id,
                debit_entry=debit_entry,
                credit_entry=credit_entry
            )
            
            logger.info(f"Successfully created ledger entries for approval: {result}")
            return {"ok": True, "ledger_entries_created": True, "result": result}
            
        except Exception as e:
            logger.error(f"Failed to create ledger entries: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling APPROVAL_RESOLVED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.post("/ledger/v4/integration/billing/invoice-posted")
async def handle_invoice_posted_event(
    event_data: Dict[str, Any] = Body(...)
):
    """Handle INVOICE_POSTED event from Billing service"""
    try:
        logger.info(f"Received INVOICE_POSTED event: {event_data}")
        
        invoice_id = event_data.get("invoice_id")
        tenant_id = event_data.get("tenant_id")
        total_amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")
        
        if not invoice_id or not tenant_id:
            raise HTTPException(status_code=400, detail="Missing invoice_id or tenant_id")
        
        # Create ledger entries for the posted invoice
        try:
            # Create debit entry (accounts receivable)
            debit_entry = {
                "tenant_id": tenant_id,
                "account": "AccountsReceivable",
                "entry_type": "debit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "invoice",
                "reference_id": invoice_id,
                "description": f"Invoice posted: {invoice_id}"
            }
            
            # Create credit entry (revenue)
            credit_entry = {
                "tenant_id": tenant_id,
                "account": "Revenue",
                "entry_type": "credit",
                "amount_minor": total_amount_minor,
                "currency": currency,
                "reference_type": "invoice",
                "reference_id": invoice_id,
                "description": f"Revenue recognized for invoice: {invoice_id}"
            }
            
            saga = LedgerEntrySaga()
            result = await saga.create_double_entry(
                tenant_id=tenant_id,
                debit_entry=debit_entry,
                credit_entry=credit_entry
            )
            
            logger.info(f"Successfully created ledger entries for invoice: {result}")
            return {"ok": True, "ledger_entries_created": True, "result": result}
            
        except Exception as e:
            logger.error(f"Failed to create ledger entries: {str(e)}")
            return {"ok": False, "error": str(e)}
            
    except Exception as e:
        logger.error(f"Error handling INVOICE_POSTED event: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle event: {str(e)}")

@app.get("/ledger/v4/integration/status")
async def get_integration_status():
    """Get status of all service integrations"""
    try:
        integration_status = {
            "orders_service": {"status": "unknown", "url": "http://localhost:8081"},
            "approvals_service": {"status": "unknown", "url": "http://localhost:8084"},
            "billing_service": {"status": "unknown", "url": "http://localhost:8083"},
            "cv_gateway_service": {"status": "unknown", "url": "http://localhost:8101"}
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
        logger.error(f"Error getting integration status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get integration status: {str(e)}")

@app.post("/ledger/v4/idempotency/cleanup")
async def cleanup_idempotency_records(
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Clean up expired idempotency records - Admin only"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        expired_count = cleanup_expired_idempotency_records(db)

        # Log audit trail
        await log_audit(
            db,
            "cleanup_idempotency_records",
            "idempotency_records",
            details={"expired_records_cleaned": expired_count},
            user_id=user_context.get("user_id"),
            tenant_id=user_context.get("tenant_id")
        )

        return {
            "ok": True,
            "expired_records_cleaned": expired_count,
            "message": f"Successfully cleaned up {expired_count} expired idempotency records"
        }

    except Exception as e:
        logger.error(f"Failed to cleanup idempotency records: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup idempotency records: {str(e)}")

@app.get("/ledger/v4/idempotency/status")
async def get_idempotency_status(
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get idempotency records status - Admin only"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Get total count of idempotency records
        total_records = db.query(IdempotencyRecord).count()

        # Get count of expired records
        expired_records = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.expires_at < datetime.now(timezone.utc)
        ).count()

        # Get count of records expiring in next hour
        next_hour = datetime.now(timezone.utc) + timedelta(hours=1)
        expiring_soon = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.expires_at < next_hour,
            IdempotencyRecord.expires_at >= datetime.now(timezone.utc)
        ).count()

        # Get oldest and newest record timestamps
        oldest_record = db.query(IdempotencyRecord).order_by(
            IdempotencyRecord.created_at.asc()
        ).first()

        newest_record = db.query(IdempotencyRecord).order_by(
            IdempotencyRecord.created_at.desc()
        ).first()

        return {
            "total_records": total_records,
            "expired_records": expired_records,
            "active_records": total_records - expired_records,
            "expiring_soon": expiring_soon,
            "oldest_record_created_at": oldest_record.created_at.isoformat() if oldest_record else None,
            "newest_record_created_at": newest_record.created_at.isoformat() if newest_record else None,
            "cleanup_recommended": expired_records > 0
        }

    except Exception as e:
        logger.error(f"Failed to get idempotency status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get idempotency status: {str(e)}")

# =============================================================================
# DAILY ROLLUPS API ENDPOINTS
# =============================================================================

@app.get("/ledger/v4/rollups/daily/{date}")
async def get_daily_rollups(
    date: str,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    account: Optional[str] = Query(None, description="Filter by account"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get daily ledger rollups for the specified date"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Parse date
        target_date = datetime.fromisoformat(date).date()

        # Get rollup data (in production, this would come from dedicated rollup tables)
        rollup_manager = DailyRollupManager(db)
        rollup_data = rollup_manager.create_daily_ledger_rollup(target_date)
        metrics_data = rollup_manager.create_daily_tenant_metrics(target_date)
        api_data = rollup_manager.create_daily_api_metrics(target_date)

        # Apply filters
        if tenant_id:
            rollup_data = [r for r in rollup_data if r['tenant_id'] == tenant_id]
            metrics_data = [m for m in metrics_data if m['tenant_id'] == tenant_id]
            api_data = [a for a in api_data if a.get('tenant_id') == tenant_id]

        if account:
            rollup_data = [r for r in rollup_data if r['account'] == account]

        if currency:
            rollup_data = [r for r in rollup_data if r['currency'] == currency]

        return {
            "date": date,
            "ledger_rollups": rollup_data,
            "tenant_metrics": metrics_data,
            "api_metrics": api_data,
            "summary": {
                "total_ledger_rollups": len(rollup_data),
                "total_tenant_metrics": len(metrics_data),
                "total_api_metrics": len(api_data)
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get daily rollups: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get daily rollups: {str(e)}")

@app.post("/ledger/v4/rollups/generate/{date}")
async def generate_rollups_for_date(
    date: str,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Manually trigger rollup generation for a specific date - Admin only"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Trigger Celery task for rollup generation
        generate_daily_ledger_rollups.delay(date)

        return {
            "ok": True,
            "message": f"Rollup generation triggered for {date}",
            "task": "generate_daily_ledger_rollups"
        }

    except Exception as e:
        logger.error(f"Failed to trigger rollup generation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger rollup generation: {str(e)}")

# =============================================================================
# ADVANCED FINANCIAL REPORTS API ENDPOINTS
# =============================================================================

@app.get("/ledger/v4/reports/pnl/{date}")
async def get_pnl_report(
    date: str,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get Profit & Loss report for the specified date"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Parse date
        target_date = datetime.fromisoformat(date).date()

        # Generate P&L data
        pnl_data = generate_pnl_summary(db, target_date)

        # Apply filters
        if tenant_id:
            pnl_data = [p for p in pnl_data if p['tenant_id'] == tenant_id]

        if currency:
            pnl_data = [p for p in pnl_data if p['currency'] == currency]

        return {
            "date": date,
            "pnl_report": pnl_data,
            "summary": {
                "total_tenants": len(set(p['tenant_id'] for p in pnl_data)),
                "total_currencies": len(set(p['currency'] for p in pnl_data)),
                "total_revenue_minor": sum(p['revenue_minor'] for p in pnl_data),
                "total_expenses_minor": sum(p['expenses_minor'] for p in pnl_data),
                "total_net_profit_minor": sum(p['net_profit_minor'] for p in pnl_data)
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to generate P&L report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate P&L report: {str(e)}")

@app.get("/ledger/v4/reports/cashflow/{date}")
async def get_cash_flow_report(
    date: str,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get Cash Flow report for the specified date"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Parse date
        target_date = datetime.fromisoformat(date).date()

        # Generate cash flow data
        cash_flow_data = generate_cash_flow_summary(db, target_date)

        # Apply filters
        if tenant_id:
            cash_flow_data = [c for c in cash_flow_data if c['tenant_id'] == tenant_id]

        if currency:
            cash_flow_data = [c for c in cash_flow_data if c['currency'] == currency]

        return {
            "date": date,
            "cash_flow_report": cash_flow_data,
            "summary": {
                "total_tenants": len(set(c['tenant_id'] for c in cash_flow_data)),
                "total_currencies": len(set(c['currency'] for c in cash_flow_data)),
                "total_inflow_minor": sum(c['cash_inflow_minor'] for c in cash_flow_data),
                "total_outflow_minor": sum(c['cash_outflow_minor'] for c in cash_flow_data),
                "net_cash_flow_minor": sum(c['net_cash_flow_minor'] for c in cash_flow_data)
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to generate cash flow report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate cash flow report: {str(e)}")

@app.get("/ledger/v4/reports/compliance/{date}")
async def get_compliance_report(
    date: str,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get Compliance report for the specified date"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Parse date
        target_date = datetime.fromisoformat(date).date()

        # Generate compliance data
        compliance_data = generate_compliance_summary(db, target_date)

        # Apply filters
        if tenant_id:
            compliance_data = [c for c in compliance_data if c['tenant_id'] == tenant_id]

        if currency:
            compliance_data = [c for c in compliance_data if c['currency'] == currency]

        return {
            "date": date,
            "compliance_report": compliance_data,
            "summary": {
                "total_tenants": len(set(c['tenant_id'] for c in compliance_data)),
                "total_transactions": sum(c['total_transactions'] for c in compliance_data),
                "total_volume_minor": sum(c['total_volume_minor'] for c in compliance_data),
                "unique_references": sum(c['unique_references'] for c in compliance_data),
                "avg_transaction_size_minor": sum(c['avg_transaction_size_minor'] for c in compliance_data) // len(compliance_data) if compliance_data else 0
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to generate compliance report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate compliance report: {str(e)}")

@app.get("/ledger/v4/reports/comprehensive/{date}")
async def get_comprehensive_financial_report(
    date: str,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get comprehensive financial report combining P&L, Cash Flow, and Compliance"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Parse date
        target_date = datetime.fromisoformat(date).date()

        # Generate all report types
        pnl_data = generate_pnl_summary(db, target_date)
        cash_flow_data = generate_cash_flow_summary(db, target_date)
        compliance_data = generate_compliance_summary(db, target_date)

        # Apply filters
        if tenant_id:
            pnl_data = [p for p in pnl_data if p['tenant_id'] == tenant_id]
            cash_flow_data = [c for c in cash_flow_data if c['tenant_id'] == tenant_id]
            compliance_data = [c for c in compliance_data if c['tenant_id'] == tenant_id]

        if currency:
            pnl_data = [p for p in pnl_data if p['currency'] == currency]
            cash_flow_data = [c for c in cash_flow_data if c['currency'] == currency]
            compliance_data = [c for c in compliance_data if c['currency'] == currency]

        return {
            "date": date,
            "comprehensive_report": {
                "pnl": pnl_data,
                "cash_flow": cash_flow_data,
                "compliance": compliance_data
            },
            "executive_summary": {
                "total_tenants": len(set(p['tenant_id'] for p in pnl_data)),
                "total_revenue_minor": sum(p['revenue_minor'] for p in pnl_data),
                "total_expenses_minor": sum(p['expenses_minor'] for p in pnl_data),
                "net_profit_minor": sum(p['net_profit_minor'] for p in pnl_data),
                "net_cash_flow_minor": sum(c['net_cash_flow_minor'] for c in cash_flow_data),
                "total_transactions": sum(c['total_transactions'] for c in compliance_data),
                "compliance_score": "High" if len(compliance_data) > 0 else "No Data"
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to generate comprehensive report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate comprehensive report: {str(e)}")

# =============================================================================
# USAGE METERING API ENDPOINTS
# =============================================================================

@app.get("/ledger/v4/usage/events/{date}")
async def get_usage_events(
    date: str,
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    meter_code: Optional[str] = Query(None, description="Filter by meter code"),
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Get usage events generated from ledger activity for the specified date"""
    # Check permissions
    if not await check_permission(user_context, "ledger.read"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Parse date
        target_date = datetime.fromisoformat(date).date()
        start_of_day = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)

        # Get usage events from ledger entries
        usage_manager = UsageMeteringManager(db)
        usage_events = usage_manager.process_ledger_entries_for_usage(start_of_day, end_of_day)

        # Apply filters
        if tenant_id:
            usage_events = [e for e in usage_events if e['tenant_id'] == tenant_id]

        if meter_code:
            usage_events = [e for e in usage_events if e['meter_code'] == meter_code]

        return {
            "date": date,
            "usage_events": usage_events,
            "summary": {
                "total_events": len(usage_events),
                "unique_tenants": len(set(e['tenant_id'] for e in usage_events)),
                "meter_codes": list(set(e['meter_code'] for e in usage_events)),
                "total_quantity": sum(e['quantity'] for e in usage_events)
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to get usage events: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get usage events: {str(e)}")

@app.post("/ledger/v4/usage/process/{date}")
async def process_usage_for_date(
    date: str,
    db: Session = Depends(get_db),
    user_context: dict = Depends(get_user_context)
):
    """Manually trigger usage processing for a specific date - Admin only"""
    # Check permissions
    if not await check_permission(user_context, "ledger.admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        # Trigger Celery task for usage processing
        process_usage_metering.delay(date)

        return {
            "ok": True,
            "message": f"Usage processing triggered for {date}",
            "task": "process_usage_metering"
        }

    except Exception as e:
        logger.error(f"Failed to trigger usage processing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger usage processing: {str(e)}")

# =============================================================================
# PHASE 7: AUDIT LOG VIEWER ENDPOINTS (Pro/Enterprise Feature)
# =============================================================================

@app.get("/audit/v7/logs")
async def get_audit_logs(
    tenant_id: str = Query(...),
    user_id: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get audit logs for tenant - Phase 7: Audit Log Viewer (Pro/Enterprise)"""
    try:
        # Check if user has audit log access permission
        if not check_permission("audit.logs.view", {"tenant_id": tenant_id, "user_id": user_id}):
            raise HTTPException(status_code=403, detail="Insufficient permissions - Audit logs require Pro or Enterprise plan")

        with SessionLocal() as db:
            query = db.query(AuditLog).filter(
                AuditLog.tenant_id == uuid.UUID(tenant_id)
            )

            # Apply filters
            if action:
                query = query.filter(AuditLog.action == action)
            if resource_type:
                query = query.filter(AuditLog.resource_type == resource_type)
            if severity:
                query = query.filter(AuditLog.severity == severity)
            if category:
                query = query.filter(AuditLog.category == category)

            # Date range filter
            try:
                start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                query = query.filter(
                    AuditLog.created_at >= start_datetime,
                    AuditLog.created_at <= end_datetime
                )
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format")

            # Get total count for pagination
            total = query.count()

            # Apply pagination and ordering
            logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

            return {
                "logs": [
                    {
                        "id": str(log.id),
                        "action": log.action,
                        "resource_type": log.resource_type,
                        "resource_id": log.resource_id,
                        "details": log.details,
                        "user_id": str(log.user_id) if log.user_id else None,
                        "ip_address": log.ip_address,
                        "created_at": log.created_at.isoformat(),
                        "severity": log.severity,
                        "category": log.category,
                        "session_id": log.session_id,
                        "correlation_id": log.correlation_id
                    }
                    for log in logs
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get audit logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/audit/v7/logs/{log_id}")
async def get_audit_log_detail(
    log_id: str,
    tenant_id: str = Query(...),
    user_id: str = Query(...)
):
    """Get detailed audit log entry - Phase 7"""
    try:
        # Check permissions
        if not check_permission("audit.logs.view", {"tenant_id": tenant_id, "user_id": user_id}):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        with SessionLocal() as db:
            log = db.query(AuditLog).filter(
                AuditLog.id == uuid.UUID(log_id),
                AuditLog.tenant_id == uuid.UUID(tenant_id)
            ).first()

            if not log:
                raise HTTPException(status_code=404, detail="Audit log not found")

            return {
                "id": str(log.id),
                "tenant_id": str(log.tenant_id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at.isoformat(),
                "session_id": log.session_id,
                "correlation_id": log.correlation_id,
                "severity": log.severity,
                "category": log.category,
                "retention_until": log.retention_until.isoformat() if log.retention_until else None
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get audit log detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting {SERVICE_NAME} service v{SERVICE_VERSION}")
    port = int(os.getenv("SERVICE_PORT", os.getenv("PORT", "8220")))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=ENVIRONMENT == "development"
    )