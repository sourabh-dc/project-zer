from typing import Dict, Any
from sqlalchemy.orm import Session

from services.payments.models import AuditLog, CustomerNew, PaymentTransactionNew, PaymentRefund


async def log_audit(db: Session, action: str, resource_type: str, resource_id: str = None,
                   details: Dict[str, Any] = None, tenant_id: str = None, user_id: str = None):
    """Log audit event"""
    audit_log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details
    )
    db.add(audit_log)
    db.commit()

async def create_customer_db(request, external_cust_id,  db: Session):
    customer = CustomerNew(
        tenant_id=request.tenant_id,
        provider=request.provider,
        external_customer_id=external_cust_id,
        email=request.email,
        name=request.name,
        phone=request.metadata.get("phone") if request.metadata else None
    )
    db.add(customer)
    db.commit()
    return customer

async def get_transaction(db: Session, request) :
    transaction = db.query(PaymentTransactionNew).filter(
        PaymentTransactionNew.payment_intent_id == request.payment_intent_id,
        PaymentTransactionNew.tenant_id == request.tenant_id
    ).first()

    return transaction

async def store_refund(db, transaction, refund_id, refund_amount, request):
    # Store refund record
    refund = PaymentRefund(
        tenant_id=request.tenant_id,
        payment_transaction_id=transaction.id,
        refund_id=refund_id,
        amount_minor=refund_amount,
        currency=transaction.currency,
        reason=request.reason,
        status="succeeded"
    )
    db.add(refund)
    db.commit()
    return refund

async def update_transaction_status(db, transaction, status):
    transaction.status = status
    db.commit()