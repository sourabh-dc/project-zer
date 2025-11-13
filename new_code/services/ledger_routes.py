import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import Body, HTTPException, Query, Depends, APIRouter
from sqlalchemy.orm import Session

from Models import LedgerEntryNew, AccountBalanceNew
from Schemas import LedgerEntryRequest, LedgerEntryResponse, AccountBalanceResponse, LedgerAdjustmentRequest
from core.db_config import get_db
from core.user_auth import get_user_context, set_rls_context
from utils.logger import logger

app = APIRouter()

@app.post("/ledger/v4/entries", response_model=dict)
async def create_ledger_entry(
        request: LedgerEntryRequest,
        user_context: Dict[str, Any] = Depends(get_user_context),
        db: Session = Depends(get_db)
):
    """Create ledger entry with direct SQLAlchemy execution"""
    try:
        set_rls_context(db, request.tenant_id)

        # Create debit entry
        debit = LedgerEntryNew(
            tenant_id=uuid.UUID(request.tenant_id),
            account=request.account,
            entry_type="debit",
            amount_minor=request.amount_minor,
            currency=request.currency,
            cost_centre_id=uuid.UUID(request.cost_centre_id) if request.cost_centre_id else None,
            site_id=uuid.UUID(request.site_id) if request.site_id else None,
            store_id=uuid.UUID(request.store_id) if request.store_id else None,
            reference_type=request.reference_type,
            reference_id=request.reference_id,
            description=request.description,
            entry_metadata=request.metadata
        )
        db.add(debit)
        db.flush()

        # Create credit entry
        credit = LedgerEntryNew(
            tenant_id=uuid.UUID(request.tenant_id),
            account="TenantClearing",
            entry_type="credit",
            amount_minor=request.amount_minor,
            currency=request.currency,
            cost_centre_id=uuid.UUID(request.cost_centre_id) if request.cost_centre_id else None,
            site_id=uuid.UUID(request.site_id) if request.site_id else None,
            store_id=uuid.UUID(request.store_id) if request.store_id else None,
            reference_type=request.reference_type,
            reference_id=request.reference_id,
            description=request.description,
            entry_metadata=request.metadata
        )
        db.add(credit)
        db.flush()

        # Update account balances
        debit_balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == uuid.UUID(request.tenant_id),
            AccountBalanceNew.account == request.account,
            AccountBalanceNew.currency == request.currency
        ).first()

        if not debit_balance:
            debit_balance = AccountBalanceNew(
                tenant_id=uuid.UUID(request.tenant_id),
                account=request.account,
                currency=request.currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            db.add(debit_balance)

        debit_balance.balance_minor += request.amount_minor
        debit_balance.last_updated = datetime.now(timezone.utc)

        # Update credit account balance
        credit_balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == uuid.UUID(request.tenant_id),
            AccountBalanceNew.account == "TenantClearing",
            AccountBalanceNew.currency == request.currency
        ).first()

        if not credit_balance:
            credit_balance = AccountBalanceNew(
                tenant_id=uuid.UUID(request.tenant_id),
                account="TenantClearing",
                currency=request.currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            db.add(credit_balance)

        credit_balance.balance_minor -= request.amount_minor
        credit_balance.last_updated = datetime.now(timezone.utc)
        db.commit()

        return {"ok": True, "entry_id": str(debit.id)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create ledger entry: {e}")
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
    try:
        set_rls_context(db, tenant_id)

        query = db.query(LedgerEntryNew).filter(LedgerEntryNew.tenant_id == uuid.UUID(tenant_id))

        if account:
            query = query.filter(LedgerEntryNew.account == account)
        if cost_centre_id:
            query = query.filter(LedgerEntryNew.cost_centre_id == uuid.UUID(cost_centre_id))
        if vendor_id:
            query = query.filter(LedgerEntryNew.vendor_id == uuid.UUID(vendor_id))
        if currency:
            query = query.filter(LedgerEntryNew.currency == currency)
        if reference_type:
            query = query.filter(LedgerEntryNew.reference_type == reference_type)

        total_count = query.count()
        entries = query.order_by(LedgerEntryNew.created_at.desc()).offset(offset).limit(limit).all()

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
                metadata=entry.entry_metadata,
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list ledger entries: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list ledger entries: {str(e)}")


@app.get("/ledger/v4/balances")
async def get_account_balances(
        tenant_id: str = Query(..., description="Tenant ID"),
        account: Optional[str] = Query(None, description="Filter by account"),
        currency: Optional[str] = Query(None, description="Filter by currency"),
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Get account balances"""
    try:
        set_rls_context(db, tenant_id)

        query = db.query(AccountBalanceNew).filter(AccountBalanceNew.tenant_id == uuid.UUID(tenant_id))

        if account:
            query = query.filter(AccountBalanceNew.account == account)
        if currency:
            query = query.filter(AccountBalanceNew.currency == currency)

        balances = query.all()

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get account balances: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get account balances: {str(e)}")


@app.post("/ledger/v4/adjustments")
async def create_ledger_adjustment(
        request: LedgerAdjustmentRequest,
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Create ledger adjustment"""
    try:
        # Get original entry
        original_entry = db.query(LedgerEntryNew).filter(
            LedgerEntryNew.id == uuid.UUID(request.entry_id)
        ).first()

        if not original_entry:
            raise HTTPException(status_code=404, detail="Entry not found")

        set_rls_context(db, str(original_entry.tenant_id))

        # Create adjustment entry
        adjustment = LedgerEntryNew(
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
            entry_metadata={
                "original_entry_id": request.entry_id,
                "adjustment_reason": request.reason,
                "adjusted_by": user_context.get("user_id")
            }
        )
        db.add(adjustment)
        db.flush()

        # Update balance
        balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == original_entry.tenant_id,
            AccountBalanceNew.account == original_entry.account,
            AccountBalanceNew.currency == original_entry.currency
        ).first()

        if balance:
            if adjustment.entry_type == "debit":
                balance.balance_minor += request.adjustment_amount_minor
            else:
                balance.balance_minor -= request.adjustment_amount_minor
            balance.last_updated = datetime.now(timezone.utc)

        db.commit()

        return {
            "ok": True,
            "adjustment_entry_id": str(adjustment.id),
            "original_entry_id": request.entry_id,
            "adjustment_amount_minor": request.adjustment_amount_minor
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create adjustment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create adjustment: {str(e)}")


@app.get("/ledger/v4/reports")
async def get_ledger_report(
        tenant_id: str = Query(..., description="Tenant ID"),
        start_date: Optional[datetime] = Query(None, description="Start date"),
        end_date: Optional[datetime] = Query(None, description="End date"),
        account: Optional[str] = Query(None, description="Filter by account"),
        cost_centre_id: Optional[str] = Query(None, description="Filter by cost centre"),
        currency: Optional[str] = Query(None, description="Filter by currency"),
        vendor_id: Optional[str] = Query(None, description="Filter by vendor"),
        include_vendor_splits: bool = Query(False, description="Include vendor revenue splits"),
        db: Session = Depends(get_db),
        user_context: dict = Depends(get_user_context)
):
    """Get ledger report with analytics"""
    try:
        set_rls_context(db, tenant_id)

        query = db.query(LedgerEntryNew).filter(LedgerEntryNew.tenant_id == uuid.UUID(tenant_id))

        if start_date:
            query = query.filter(LedgerEntryNew.created_at >= start_date)
        if end_date:
            query = query.filter(LedgerEntryNew.created_at <= end_date)
        if account:
            query = query.filter(LedgerEntryNew.account == account)
        if cost_centre_id:
            query = query.filter(LedgerEntryNew.cost_centre_id == uuid.UUID(cost_centre_id))
        if currency:
            query = query.filter(LedgerEntryNew.currency == currency)
        if vendor_id:
            query = query.filter(LedgerEntryNew.vendor_id == uuid.UUID(vendor_id))

        entries = query.all()

        # Aggregate by account and currency
        account_summary = {}
        vendor_summary = {} if include_vendor_splits else None

        for entry in entries:
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

                if entry.entry_type == "debit":
                    vendor_summ["total_revenue_minor"] += entry.amount_minor
                    vendor_summ["net_revenue_minor"] += entry.amount_minor
                else:
                    vendor_summ["total_expenses_minor"] += entry.amount_minor
                    vendor_summ["net_revenue_minor"] -= entry.amount_minor

        result = {
            "tenant_id": tenant_id,
            "period": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None
            },
            "filters": {
                "account": account,
                "cost_centre_id": cost_centre_id,
                "currency": currency,
                "vendor_id": vendor_id
            },
            "summary": list(account_summary.values()),
            "total_entries": len(entries),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

        if include_vendor_splits and vendor_summary:
            result["vendor_splits"] = list(vendor_summary.values())

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


# =============================================================================
# EVENT HANDLERS
# =============================================================================

@app.post("/ledger/v4/events/order-completed")
async def handle_order_completed(
        event_data: dict = Body(...),
        db: Session = Depends(get_db)
):
    """Handle ORDER_COMPLETED event from Orders service"""
    try:
        tenant_id = event_data.get("tenant_id")
        order_id = event_data.get("order_id")
        amount_minor = event_data.get("total_amount_minor", 0)
        currency = event_data.get("currency", "GBP")

        if not tenant_id or not order_id or amount_minor <= 0:
            return {"ok": False, "message": "Invalid event data"}

        # Create debit entry
        debit = LedgerEntryNew(
            tenant_id=uuid.UUID(tenant_id),
            account="CostCentreSpend",
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="order",
            reference_id=order_id,
            description=f"Order completion: {order_id}",
            entry_metadata={"event_source": "order_completed"}
        )
        db.add(debit)
        db.flush()

        # Create credit entry
        credit = LedgerEntryNew(
            tenant_id=uuid.UUID(tenant_id),
            account="TenantClearing",
            entry_type="credit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="order",
            reference_id=order_id,
            description=f"Order completion: {order_id}",
            entry_metadata={"event_source": "order_completed"}
        )
        db.add(credit)
        db.flush()

        # Update balances
        debit_balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == uuid.UUID(tenant_id),
            AccountBalanceNew.account == "CostCentreSpend",
            AccountBalanceNew.currency == currency
        ).first()

        if not debit_balance:
            debit_balance = AccountBalanceNew(
                tenant_id=uuid.UUID(tenant_id),
                account="CostCentreSpend",
                currency=currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            db.add(debit_balance)

        debit_balance.balance_minor += amount_minor
        debit_balance.last_updated = datetime.now(timezone.utc)

        credit_balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == uuid.UUID(tenant_id),
            AccountBalanceNew.account == "TenantClearing",
            AccountBalanceNew.currency == currency
        ).first()

        if not credit_balance:
            credit_balance = AccountBalanceNew(
                tenant_id=uuid.UUID(tenant_id),
                account="TenantClearing",
                currency=currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            db.add(credit_balance)

        credit_balance.balance_minor -= amount_minor
        credit_balance.last_updated = datetime.now(timezone.utc)

        db.commit()

        return {"ok": True, "ledger_entry_id": str(debit.id)}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to handle order completed event: {e}")
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

        # Create debit entry
        debit = LedgerEntryNew(
            tenant_id=uuid.UUID(tenant_id),
            account="AccountsReceivable",
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="invoice",
            reference_id=invoice_id,
            description=f"Invoice posted: {invoice_id}",
            entry_metadata={"event_source": "invoice_posted"}
        )
        db.add(debit)
        db.flush()

        # Create credit entry
        credit = LedgerEntryNew(
            tenant_id=uuid.UUID(tenant_id),
            account="Revenue",
            entry_type="credit",
            amount_minor=amount_minor,
            currency=currency,
            reference_type="invoice",
            reference_id=invoice_id,
            description=f"Invoice posted: {invoice_id}",
            entry_metadata={"event_source": "invoice_posted"}
        )
        db.add(credit)
        db.flush()

        # Update balances
        debit_balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == uuid.UUID(tenant_id),
            AccountBalanceNew.account == "AccountsReceivable",
            AccountBalanceNew.currency == currency
        ).first()

        if not debit_balance:
            debit_balance = AccountBalanceNew(
                tenant_id=uuid.UUID(tenant_id),
                account="AccountsReceivable",
                currency=currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            db.add(debit_balance)

        debit_balance.balance_minor += amount_minor
        debit_balance.last_updated = datetime.now(timezone.utc)

        credit_balance = db.query(AccountBalanceNew).filter(
            AccountBalanceNew.tenant_id == uuid.UUID(tenant_id),
            AccountBalanceNew.account == "Revenue",
            AccountBalanceNew.currency == currency
        ).first()

        if not credit_balance:
            credit_balance = AccountBalanceNew(
                tenant_id=uuid.UUID(tenant_id),
                account="Revenue",
                currency=currency,
                balance_minor=0,
                last_updated=datetime.now(timezone.utc)
            )
            db.add(credit_balance)

        credit_balance.balance_minor -= amount_minor
        credit_balance.last_updated = datetime.now(timezone.utc)

        db.commit()

        return {"ok": True, "ledger_entry_id": str(debit.id)}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to handle invoice posted event: {e}")
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
            # Create debit entry
            debit = LedgerEntryNew(
                tenant_id=uuid.UUID(tenant_id),
                account="BudgetAllocation",
                entry_type="debit",
                amount_minor=amount_minor,
                currency=currency,
                reference_type="approval",
                reference_id=request_id,
                description=f"Budget allocated: {request_id}",
                entry_metadata={"event_source": "approval_resolved"}
            )
            db.add(debit)
            db.flush()

            # Create credit entry
            credit = LedgerEntryNew(
                tenant_id=uuid.UUID(tenant_id),
                account="TenantClearing",
                entry_type="credit",
                amount_minor=amount_minor,
                currency=currency,
                reference_type="approval",
                reference_id=request_id,
                description=f"Budget allocated: {request_id}",
                entry_metadata={"event_source": "approval_resolved"}
            )
            db.add(credit)
            db.flush()

            # Update balances
            debit_balance = db.query(AccountBalanceNew).filter(
                AccountBalanceNew.tenant_id == uuid.UUID(tenant_id),
                AccountBalanceNew.account == "BudgetAllocation",
                AccountBalanceNew.currency == currency
            ).first()

            if not debit_balance:
                debit_balance = AccountBalanceNew(
                    tenant_id=uuid.UUID(tenant_id),
                    account="BudgetAllocation",
                    currency=currency,
                    balance_minor=0,
                    last_updated=datetime.now(timezone.utc)
                )
                db.add(debit_balance)

            debit_balance.balance_minor += amount_minor
            debit_balance.last_updated = datetime.now(timezone.utc)

            credit_balance = db.query(AccountBalanceNew).filter(
                AccountBalanceNew.tenant_id == uuid.UUID(tenant_id),
                AccountBalanceNew.account == "TenantClearing",
                AccountBalanceNew.currency == currency
            ).first()

            if not credit_balance:
                credit_balance = AccountBalanceNew(
                    tenant_id=uuid.UUID(tenant_id),
                    account="TenantClearing",
                    currency=currency,
                    balance_minor=0,
                    last_updated=datetime.now(timezone.utc)
                )
                db.add(credit_balance)

            credit_balance.balance_minor -= amount_minor
            credit_balance.last_updated = datetime.now(timezone.utc)

            db.commit()

            return {"ok": True, "ledger_entry_id": str(debit.id)}
        else:
            return {"ok": True, "message": "No ledger entry needed for denied approval"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to handle approval resolved event: {e}")
        return {"ok": False, "error": str(e)}


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

