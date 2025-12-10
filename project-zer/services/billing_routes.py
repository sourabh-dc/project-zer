import uuid
import json
from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, Query, APIRouter
from sqlalchemy import or_
from sqlalchemy.orm import Session

from Models import TradeInvoice, TradeInvoiceLine, BillingOutboxEvent, VendorSettlementBatch, VendorSettlement, \
    VendorSettlementItem, VendorDispute, CostCentre, Budget, BudgetTransaction, BudgetAlert
from Schemas import CreateInvoiceRequest, InvoiceResponse, CreateSettlementRequest, SettlementResponse, \
    CreateDisputeRequest, DisputeResponse, CostCentreRequest, CostCentreResponse, BudgetResponse, BudgetRequest, \
    BudgetCheckResponse, BudgetCheckRequest, SpendRequest
from core.db_config import get_db
from core.user_auth import get_user_context, set_rls_context
from utils.logger import logger

app = APIRouter()

@app.post("/billing/v2/invoices", response_model=InvoiceResponse)
async def create_invoice(
        request: CreateInvoiceRequest,
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Create a new invoice"""
    try:
        invoice_id = f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

        invoice = TradeInvoice(
            id=invoice_id,
            tenant_id=request.tenant_id,
            invoice_number=request.invoice_number or f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            status='draft',
            amount_minor=request.total_minor,
            currency=request.currency,
            tax_total_minor=request.tax_total_minor,
            subtotal_minor=request.subtotal_minor,
            due_date=request.due_date,
            ar_customer_code=request.ar_customer_code,
            terms=request.terms
        )
        db.add(invoice)
        db.flush()

        for line in request.lines:
            invoice_line = TradeInvoiceLine(
                invoice_id=invoice_id,
                line_number=line.line_number,
                description=line.description,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                line_total_minor=line.line_total_minor,
                tax_minor=line.tax_minor,
                tax_code=line.tax_code
            )
            db.add(invoice_line)

        invoice.status = 'posted'
        invoice.posted_at = datetime.now(timezone.utc)

        outbox_event = BillingOutboxEvent(
            aggregate_id=uuid.uuid4(),
            event_type="INVOICE_CREATED",
            event_data=json.dumps({
                "invoice_id": invoice_id,
                "tenant_id": request.tenant_id,
                "amount_minor": request.total_minor,
                "currency": request.currency,
                "status": "posted",
                "created_at": datetime.now(timezone.utc).isoformat()
            }),
            status="pending"
        )
        db.add(outbox_event)
        db.commit()
        db.refresh(invoice)

        lines = db.query(TradeInvoiceLine).filter(TradeInvoiceLine.invoice_id == invoice_id).all()

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
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create invoice: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")


@app.get("/billing/v2/invoices")
async def list_invoices(
        tenant_id: str = Query(..., description="Tenant ID"),
        status: Optional[str] = Query(None, description="Invoice status filter"),
        start_date: Optional[date] = Query(None, description="Start date filter"),
        end_date: Optional[date] = Query(None, description="End date filter"),
        limit: int = Query(100, description="Number of results to return"),
        offset: int = Query(0, description="Number of results to skip"),
        db: Session = Depends(get_db)
):
    """List invoices with filtering and pagination"""
    try:
        set_rls_context(db, tenant_id)

        query = db.query(TradeInvoice).filter(TradeInvoice.tenant_id == tenant_id)

        if status:
            query = query.filter(TradeInvoice.status == status)
        if start_date:
            query = query.filter(TradeInvoice.created_at >= start_date)
        if end_date:
            query = query.filter(TradeInvoice.created_at <= end_date)

        total_count = query.count()
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
        logger.error(f"Failed to list invoices: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list invoices: {str(e)}")


@app.post("/billing/v2/settlements", response_model=SettlementResponse)
async def create_settlement(
        request: CreateSettlementRequest,
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Create a new vendor settlement"""
    try:
        settlement_id = uuid.uuid4()
        batch_id = uuid.uuid4()

        total_sales = sum(item.payout_amount_minor for item in request.items)
        total_commission = sum(item.commission_amount_minor for item in request.items)
        net_settlement = sum(item.net_amount_minor for item in request.items)

        batch = VendorSettlementBatch(
            id=batch_id,
            tenant_id=uuid.UUID(request.tenant_id),
            batch_number=f"BATCH-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            period_start=request.settlement_period_start,
            period_end=request.settlement_period_end,
            status='processing',
            total_amount_minor=net_settlement,
            settlement_count=len(request.items)
        )
        db.add(batch)
        db.flush()

        settlement = VendorSettlement(
            settlement_id=settlement_id,
            vendor_id=uuid.UUID(request.vendor_id),
            tenant_id=uuid.UUID(request.tenant_id),
            settlement_period_start=request.settlement_period_start,
            settlement_period_end=request.settlement_period_end,
            total_sales_minor=total_sales,
            total_commission_minor=total_commission,
            net_settlement_minor=net_settlement,
            currency=request.currency,
            settlement_status='processed',
            settlement_date=datetime.now(timezone.utc)
        )
        db.add(settlement)
        db.flush()

        for item in request.items:
            settlement_item = VendorSettlementItem(
                batch_id=batch_id,
                settlement_id=settlement_id,
                vendor_id=uuid.UUID(request.vendor_id),
                tenant_id=uuid.UUID(request.tenant_id),
                payout_amount_minor=item.payout_amount_minor,
                commission_amount_minor=item.commission_amount_minor,
                fee_amount_minor=item.fee_amount_minor,
                net_amount_minor=item.net_amount_minor,
                settlement_status='processed'
            )
            db.add(settlement_item)

        db.commit()

        return SettlementResponse(
            settlement_id=str(settlement_id),
            vendor_id=request.vendor_id,
            tenant_id=request.tenant_id,
            settlement_period_start=request.settlement_period_start,
            settlement_period_end=request.settlement_period_end,
            total_sales_minor=total_sales,
            total_commission_minor=total_commission,
            net_settlement_minor=net_settlement,
            currency=request.currency,
            settlement_status='processed',
            settlement_date=settlement.settlement_date,
            created_at=settlement.created_at
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create settlement: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create settlement: {str(e)}")


@app.get("/billing/v2/settlements")
async def list_settlements(
        tenant_id: str = Query(..., description="Tenant ID"),
        vendor_id: Optional[str] = Query(None, description="Vendor ID filter"),
        status: Optional[str] = Query(None, description="Settlement status filter"),
        start_date: Optional[date] = Query(None, description="Start date filter"),
        end_date: Optional[date] = Query(None, description="End date filter"),
        limit: int = Query(100, description="Number of results to return"),
        offset: int = Query(0, description="Number of results to skip"),
        db: Session = Depends(get_db)
):
    """List settlements with filtering and pagination"""
    try:
        set_rls_context(db, tenant_id)

        query = db.query(VendorSettlement).filter(VendorSettlement.tenant_id == uuid.UUID(tenant_id))

        if vendor_id:
            query = query.filter(VendorSettlement.vendor_id == uuid.UUID(vendor_id))
        if status:
            query = query.filter(VendorSettlement.settlement_status == status)
        if start_date:
            query = query.filter(VendorSettlement.settlement_period_start >= start_date)
        if end_date:
            query = query.filter(VendorSettlement.settlement_period_end <= end_date)

        total_count = query.count()
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
        logger.error(f"Failed to list settlements: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list settlements: {str(e)}")


@app.post("/billing/v2/disputes", response_model=DisputeResponse)
async def create_dispute(
        request: CreateDisputeRequest,
        db: Session = Depends(get_db)
):
    """Create a new dispute"""
    try:
        set_rls_context(db, request.tenant_id)

        if not request.settlement_id and not request.settlement_item_id:
            raise HTTPException(status_code=400, detail="Either settlement_id or settlement_item_id must be provided")

        dispute = VendorDispute(
            settlement_item_id=uuid.UUID(request.settlement_item_id) if request.settlement_item_id else uuid.UUID(
                request.settlement_id),
            vendor_id=uuid.UUID("550e8400-e29b-41d4-a716-446655440008"),
            dispute_type="amount_dispute",
            dispute_reason=request.dispute_reason,
            status='open',
            sla_deadline=datetime.now(timezone.utc) + timedelta(days=7),
            tenant_id=uuid.UUID(request.tenant_id)
        )

        db.add(dispute)
        db.commit()
        db.refresh(dispute)

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
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create dispute: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create dispute: {str(e)}")


@app.post("/cost-centres", response_model=CostCentreResponse)
async def create_cost_centre(
        request: CostCentreRequest,
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Create a new cost centre - Phase 4"""
    try:
        cost_centre = CostCentre(
            tenant_id=uuid.UUID(user_context["tenant_id"]),
            name=request.name,
            code=request.code,
            description=request.description,
            parent_cost_centre_id=uuid.UUID(request.parent_cost_centre_id) if request.parent_cost_centre_id else None,
            budget_owner_id=uuid.UUID(request.budget_owner_id)
        )

        db.add(cost_centre)
        db.commit()
        db.refresh(cost_centre)

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
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create cost centre: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cost-centres")
async def list_cost_centres(
        tenant_id: str = Query(...),
        parent_cost_centre_id: Optional[str] = Query(None),
        limit: int = Query(100, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
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
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Create a new budget - Phase 4"""
    try:
        cost_centre = db.query(CostCentre).filter(
            CostCentre.cost_centre_id == uuid.UUID(request.cost_centre_id),
            CostCentre.tenant_id == uuid.UUID(user_context["tenant_id"])
        ).first()

        if not cost_centre:
            raise HTTPException(status_code=404, detail="Cost centre not found")

        budget = Budget(
            cost_centre_id=uuid.UUID(request.cost_centre_id),
            tenant_id=uuid.UUID(user_context["tenant_id"]),
            budget_year=request.budget_year,
            budget_month=request.budget_month or 1,
            budget_type=request.budget_type,
            budget_amount_minor=request.budget_amount_minor,
            available_amount_minor=request.budget_amount_minor,
            currency=request.currency,
            approval_workflow_id=uuid.UUID(request.approval_workflow_id) if request.approval_workflow_id else None
        )

        db.add(budget)
        db.commit()
        db.refresh(budget)

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
        db.rollback()
        logger.error(f"Failed to create budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/budgets/{budget_id}")
async def get_budget_details(
        budget_id: str,
        db: Session = Depends(get_db)
):
    """Get budget details with transactions - Phase 4"""
    try:
        budget = db.query(Budget).filter(Budget.budget_id == uuid.UUID(budget_id)).first()

        if not budget:
            raise HTTPException(status_code=404, detail="Budget not found")

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


@app.post("/budget-check", response_model=BudgetCheckResponse)
async def check_budget(
        request: BudgetCheckRequest,
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Check if budget allows spend and trigger approval if needed - Phase 4"""
    try:
        current_year = datetime.now().year
        current_month = datetime.now().month

        budget = db.query(Budget).join(CostCentre).filter(
            Budget.cost_centre_id == uuid.UUID(request.cost_centre_id),
            Budget.tenant_id == uuid.UUID(user_context["tenant_id"]),
            CostCentre.tenant_id == uuid.UUID(user_context["tenant_id"]),
            Budget.budget_year == current_year,
            Budget.is_active == True,
            or_(Budget.budget_month == current_month, Budget.budget_type == "annual")
        ).first()

        if not budget:
            raise HTTPException(status_code=404, detail="No active budget found for cost centre")

        available_amount = budget.available_amount_minor
        requested_amount = request.amount_minor

        if available_amount >= requested_amount:
            approval_required = False
            approval_id = None
            is_approved = True
            message = "Budget check passed - sufficient funds available"
        else:
            approval_required = True
            is_approved = False
            approval_id = None
            message = "Budget check failed - insufficient funds"

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
        logger.error(f"Failed to check budget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/spend")
async def record_spend(
        request: SpendRequest,
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Record spend against budget - Phase 4"""
    try:
        current_year = datetime.now().year
        current_month = datetime.now().month

        budget = db.query(Budget).filter(
            Budget.cost_centre_id == uuid.UUID(request.cost_centre_id),
            Budget.tenant_id == uuid.UUID(user_context["tenant_id"]),
            Budget.budget_year == current_year,
            Budget.is_active == True,
            or_(Budget.budget_month == current_month, Budget.budget_type == "annual")
        ).first()

        if not budget:
            raise HTTPException(status_code=404, detail="No active budget found for cost centre")

        transaction = BudgetTransaction(
            budget_id=budget.budget_id,
            tenant_id=uuid.UUID(user_context["tenant_id"]),
            amount_minor=request.amount_minor,
            transaction_type="spend",
            description=request.description,
            reference_id=request.reference_id,
            reference_type=request.reference_type,
            approval_id=uuid.UUID(request.approval_id) if request.approval_id else None,
            is_approved=True,
            created_by=uuid.UUID(user_context["user_id"])
        )

        db.add(transaction)

        budget.spent_amount_minor += request.amount_minor
        budget.available_amount_minor = budget.budget_amount_minor - budget.spent_amount_minor

        if budget.spent_amount_minor > budget.budget_amount_minor:
            budget.status = "exceeded"

            alert = BudgetAlert(
                budget_id=budget.budget_id,
                tenant_id=uuid.UUID(user_context["tenant_id"]),
                alert_type="exceeded",
                threshold_percentage=100.00,
                message=f"Budget exceeded by {budget.spent_amount_minor - budget.budget_amount_minor} minor units"
            )
            db.add(alert)

        db.commit()

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
        db.rollback()
        logger.error(f"Failed to record spend: {e}")
        raise HTTPException(status_code=500, detail=str(e))

