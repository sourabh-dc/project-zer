from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session

from core.db_config import get_db
from Models import (
    Order,
    OrderItem,
    LedgerEntryNew as LedgerEntry,
    AccountBalanceNew as AccountBalance,
)
from operations.ledger import record_order_ledger, record_entry_pair

router = APIRouter(prefix="/operations/ledger", tags=["operations"])


@router.post("/orders/{order_id}/post")
async def post_order_to_ledger(order_id: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    res = record_order_ledger(order, items, source="aifi", db=db)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("reason"))
    return res


@router.get("/entries")
async def list_entries(
    tenant_id: Optional[str] = Query(None),
    order_id: Optional[str] = Query(None),
    account: Optional[str] = Query(None),
    reference_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(LedgerEntry)
    if tenant_id:
        q = q.filter(LedgerEntry.tenant_id == tenant_id)
    if order_id:
        q = q.filter(LedgerEntry.reference_type == "order", LedgerEntry.reference_id == order_id)
    if account:
        q = q.filter(LedgerEntry.account == account)
    if reference_type:
        q = q.filter(LedgerEntry.reference_type == reference_type)
    total = q.count()
    entries = q.order_by(LedgerEntry.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": str(e.id),
                "tenant_id": str(e.tenant_id),
                "account": e.account,
                "entry_type": e.entry_type,
                "amount_minor": e.amount_minor,
                "currency": e.currency,
                "store_id": str(e.store_id) if e.store_id else None,
                "reference_type": e.reference_type,
                "reference_id": e.reference_id,
                "created_at": e.created_at,
                "metadata": e.entry_metadata,
            }
            for e in entries
        ],
    }


@router.get("/balances")
async def list_balances(
    tenant_id: str = Query(...),
    account: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(AccountBalance).filter(AccountBalance.tenant_id == tenant_id)
    if account:
        q = q.filter(AccountBalance.account == account)
    if currency:
        q = q.filter(AccountBalance.currency == currency)
    balances = q.all()
    return [
        {
            "account": b.account,
            "currency": b.currency,
            "balance_minor": b.balance_minor,
            "last_updated": b.last_updated,
        }
        for b in balances
    ]


@router.post("/entries/pair")
async def create_entry_pair(payload: dict = Body(...), db: Session = Depends(get_db)):
    required = ["tenant_id", "amount_minor", "currency", "account_debit", "account_credit"]
    for key in required:
        if key not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field {key}")
    res = record_entry_pair(
        tenant_id=payload["tenant_id"],
        amount_minor=int(payload["amount_minor"]),
        currency=payload["currency"],
        account_debit=payload["account_debit"],
        account_credit=payload["account_credit"],
        reference_type=payload.get("reference_type"),
        reference_id=payload.get("reference_id"),
        description=payload.get("description"),
        metadata=payload.get("metadata"),
        cost_centre_id=payload.get("cost_centre_id"),
        site_id=payload.get("site_id"),
        store_id=payload.get("store_id"),
        idempotency_key=payload.get("idempotency_key"),
        db=db,
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("reason"))
    return res


@router.get("/reports")
async def ledger_report(
    tenant_id: str = Query(...),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    account: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(LedgerEntry).filter(LedgerEntry.tenant_id == tenant_id)
    if start_date:
        q = q.filter(LedgerEntry.created_at >= start_date)
    if end_date:
        q = q.filter(LedgerEntry.created_at <= end_date)
    if account:
        q = q.filter(LedgerEntry.account == account)
    if currency:
        q = q.filter(LedgerEntry.currency == currency)

    summary = {}
    entries = q.all()
    for e in entries:
        key = f"{e.account}_{e.currency}"
        if key not in summary:
            summary[key] = {
                "account": e.account,
                "currency": e.currency,
                "total_debits_minor": 0,
                "total_credits_minor": 0,
                "net_minor": 0,
                "entry_count": 0,
            }
        s = summary[key]
        s["entry_count"] += 1
        if e.entry_type == "debit":
            s["total_debits_minor"] += e.amount_minor
            s["net_minor"] += e.amount_minor
        else:
            s["total_credits_minor"] += e.amount_minor
            s["net_minor"] -= e.amount_minor

    return {
        "tenant_id": tenant_id,
        "period": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
        "summary": list(summary.values()),
        "total_entries": len(entries),
    }

