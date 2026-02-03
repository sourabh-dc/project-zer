import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List

from sqlalchemy.orm import Session

from operations_service.Models import (
    LedgerEntryNew as LedgerEntry,
    AccountBalanceNew as AccountBalance,
    Order,
    OrderItem,
)
from operations_service.core.db_config import SessionLocal
from operations_service.utils.logger import logger


def _items_summary(items: List[OrderItem]) -> List[Dict]:
    return [
        {
            "product_id": str(i.product_id),
            "quantity": i.quantity,
            "unit_price_minor": i.unit_price_minor,
            "total_price_minor": i.total_price_minor,
        }
        for i in items
    ]


def _already_posted(db: Session, order_id: uuid.UUID, source: str) -> bool:
    return (
        db.query(LedgerEntry)
        .filter(
            LedgerEntry.reference_type == "order",
            LedgerEntry.reference_id == str(order_id),
            LedgerEntry.entry_metadata["source"].astext == source,
        )
        .first()
        is not None
    )


def _upsert_balance(db: Session, tenant_id, account, currency, delta):
    bal = (
        db.query(AccountBalance)
        .filter(
            AccountBalance.tenant_id == tenant_id,
            AccountBalance.account == account,
            AccountBalance.currency == currency,
        )
        .first()
    )
    if not bal:
        bal = AccountBalance(
            tenant_id=tenant_id,
            account=account,
            currency=currency,
            balance_minor=0,
            last_updated=datetime.now(timezone.utc),
        )
        db.add(bal)
    bal.balance_minor += delta
    bal.last_updated = datetime.now(timezone.utc)


def record_order_ledger(order: Order, items: List[OrderItem], source: str = "aifi", db: Optional[Session] = None) -> Dict:
    """
    Record double-entry for an order:
      - Debit: CostCentreSpend (or general spend) with cost_centre_id if available
      - Credit: Revenue
    Idempotent by order_id + source.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        if _already_posted(db, order.order_id, source):
            return {"status": "skipped", "reason": "already_posted"}

        total = order.total_amount_minor or 0
        if total <= 0:
            return {"status": "skipped", "reason": "zero_total"}

        currency = order.currency or "GBP"
        tenant_id = order.tenant_id
        store_id = order.store_id
        cost_centre_id = None  # optional: if you want to pass it in metadata, set it below

        metadata = {
            "source": source,
            "order_id": str(order.order_id),
            "aifi_order_id": order.order_metadata.get("aifi_order_id") if order.order_metadata else None,
            "store_id": str(store_id) if store_id else None,
            "customer_id": str(order.customer_id),
            "items": _items_summary(items),
        }

        # Debit
        debit = LedgerEntry(
            tenant_id=tenant_id,
            account="CostCentreSpend",
            entry_type="debit",
            amount_minor=total,
            currency=currency,
            cost_centre_id=cost_centre_id,
            site_id=order.site_id,
            store_id=store_id,
            reference_type="order",
            reference_id=str(order.order_id),
            description="Order posted",
            entry_metadata=metadata,
        )
        db.add(debit)
        db.flush()

        # Credit
        credit = LedgerEntry(
            tenant_id=tenant_id,
            account="Revenue",
            entry_type="credit",
            amount_minor=total,
            currency=currency,
            cost_centre_id=cost_centre_id,
            site_id=order.site_id,
            store_id=store_id,
            reference_type="order",
            reference_id=str(order.order_id),
            description="Order posted",
            entry_metadata=metadata,
        )
        db.add(credit)
        db.flush()

        # Balances
        _upsert_balance(db, tenant_id, "CostCentreSpend", currency, total)
        _upsert_balance(db, tenant_id, "Revenue", currency, -total)

        db.commit()
        return {"status": "ok", "debit_id": str(debit.id), "credit_id": str(credit.id)}
    except Exception as exc:
        db.rollback()
        logger.error(f"record_order_ledger failed: {exc}")
        return {"status": "error", "reason": str(exc)}
    finally:
        if close_db:
            db.close()


def record_entry_pair(
    *,
    tenant_id,
    amount_minor: int,
    currency: str,
    account_debit: str,
    account_credit: str,
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict] = None,
    cost_centre_id=None,
    site_id=None,
    store_id=None,
    idempotency_key: Optional[str] = None,
    db: Optional[Session] = None,
) -> Dict:
    """
    Generic helper to post a debit/credit pair with optional idempotency.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        if idempotency_key:
            exists = (
                db.query(LedgerEntry)
                .filter(
                    LedgerEntry.entry_metadata["idempotency_key"].astext == idempotency_key,
                    LedgerEntry.tenant_id == tenant_id,
                )
                .first()
            )
            if exists:
                return {"status": "skipped", "reason": "idempotent", "entry_id": str(exists.id)}

        meta = metadata or {}
        if idempotency_key:
            meta = {**meta, "idempotency_key": idempotency_key}

        debit = LedgerEntry(
            tenant_id=tenant_id,
            account=account_debit,
            entry_type="debit",
            amount_minor=amount_minor,
            currency=currency,
            cost_centre_id=cost_centre_id,
            site_id=site_id,
            store_id=store_id,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            entry_metadata=meta,
        )
        db.add(debit)
        db.flush()

        credit = LedgerEntry(
            tenant_id=tenant_id,
            account=account_credit,
            entry_type="credit",
            amount_minor=amount_minor,
            currency=currency,
            cost_centre_id=cost_centre_id,
            site_id=site_id,
            store_id=store_id,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            entry_metadata=meta,
        )
        db.add(credit)
        db.flush()

        _upsert_balance(db, tenant_id, account_debit, currency, amount_minor)
        _upsert_balance(db, tenant_id, account_credit, currency, -amount_minor)

        db.commit()
        return {"status": "ok", "debit_id": str(debit.id), "credit_id": str(credit.id)}
    except Exception as exc:
        db.rollback()
        logger.error(f"record_entry_pair failed: {exc}")
        return {"status": "error", "reason": str(exc)}
    finally:
        if close_db:
            db.close()

