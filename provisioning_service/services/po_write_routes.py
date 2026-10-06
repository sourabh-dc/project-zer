"""
Governed ERP write API (deck slice 5).

POST /v1/tenants/{tid}/connections/{cid}/create-purchase-order
  → four gates → idempotency check → ERP write → ack recorded.
  Never claim success until the ERP acknowledged. Every attempt leaves
  a PurchaseOrderWrite audit row.

POST /v1/tenants/{tid}/po-writes/{write_id}/retry
  → re-attempt a failed write with the SAME idempotency key — the ERP
  must not create a second PO.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from provisioning_service import Models
from provisioning_service.core.connectors.base import ConnectorError
from provisioning_service.core.connectors.engine import build_connector, classify_error
from provisioning_service.core.connectors.gates import WRITE_PERMISSION, check_write_gates
from provisioning_service.core.db_config import get_db
from provisioning_service.core.user_auth import check_user_authorization
from provisioning_service.utils.logger import logger

router = APIRouter(prefix="/v1", tags=["ERP Write-back"])


class PurchaseOrderLine(BaseModel):
    sku: str
    description: Optional[str] = None
    quantity: int = Field(gt=0)
    unit_price_minor: int = Field(ge=0)
    supplier_sku: Optional[str] = None
    unit: str = "EA"


class CreatePOWriteRequest(BaseModel):
    order_id: str                                    # ZeroQue PO id
    order_status: str                                # gate 4 input
    idempotency_key: str = Field(min_length=8, max_length=100)
    vendor_external_id: str                          # ERP-native vendor id
    currency: str = "GBP"
    lines: List[PurchaseOrderLine] = Field(min_length=1)
    ship_to: Optional[Dict[str, Any]] = None
    memo: Optional[str] = None


class POWriteOut(BaseModel):
    write_id: str
    status: str
    gates: Dict[str, bool]
    erp_response: Optional[Dict[str, Any]] = None
    attempt_count: int
    idempotency_key: str


def _check_tenant(ctx, tenant_id: str) -> None:
    if str(ctx.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tenant")


def _write_out(w: Models.PurchaseOrderWrite) -> POWriteOut:
    return POWriteOut(
        write_id=str(w.write_id),
        status=w.status,
        gates=w.gates or {},
        erp_response=w.erp_response,
        attempt_count=w.attempt_count,
        idempotency_key=w.idempotency_key,
    )


def _attempt_erp_write(db: Session, write: Models.PurchaseOrderWrite, connection: Models.TenantConnection) -> Models.PurchaseOrderWrite:
    """Call the adapter's createPurchaseOrder and record the outcome."""
    connector = build_connector(connection)
    write.attempt_count += 1
    write.last_attempt_at = datetime.now(timezone.utc)
    try:
        response = connector.create_purchase_order(write.payload, idempotency_key=write.idempotency_key)
        write.status = "acknowledged"
        write.erp_response = response
    except ConnectorError as e:
        write.status = "failed"
        write.erp_response = {"error": str(e), "retry_class": classify_error(e)}
    except Exception as e:
        write.status = "failed"
        write.erp_response = {"error": f"unexpected: {e}", "retry_class": classify_error(e)}
        logger.error(f"PO write {write.write_id} attempt {write.attempt_count} failed: {e}")
    db.commit()
    db.refresh(write)
    return write


@router.post(
    "/tenants/{tenant_id}/connections/{connection_id}/create-purchase-order",
    response_model=POWriteOut,
    status_code=201,
)
def create_purchase_order(
    tenant_id: str,
    connection_id: str,
    req: CreatePOWriteRequest,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(WRITE_PERMISSION)),
):
    """Governed write: gates → idempotency → ERP → ack. Never silent."""
    _check_tenant(ctx, tenant_id)

    connection = db.query(Models.TenantConnection).filter(
        Models.TenantConnection.connection_id == connection_id,
        Models.TenantConnection.tenant_id == tenant_id,
    ).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Idempotency: same key → return the existing audit row, no second ERP call
    existing = db.query(Models.PurchaseOrderWrite).filter(
        Models.PurchaseOrderWrite.idempotency_key == req.idempotency_key,
    ).first()
    if existing:
        return _write_out(existing)

    connector = build_connector(connection)
    is_admin = "*" in (ctx.get("permissions") or [])
    gate_result = check_write_gates(
        db,
        connector=connector,
        tenant_id=tenant_id,
        user_permissions=ctx.get("permissions") or [],
        order_status=req.order_status,
        is_admin=is_admin,
    )

    payload = {
        "order_id": req.order_id,
        "vendor_external_id": req.vendor_external_id,
        "currency": req.currency,
        "lines": [line.model_dump() for line in req.lines],
        "ship_to": req.ship_to,
        "memo": req.memo,
        "total_minor": sum(l.quantity * l.unit_price_minor for l in req.lines),
    }

    write = Models.PurchaseOrderWrite(
        write_id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        connection_id=connection.connection_id,
        order_id=req.order_id,
        idempotency_key=req.idempotency_key,
        gates=gate_result["gates"],
        payload=payload,
        status="pending",
        created_by=uuid.UUID(ctx["user_id"]) if ctx.get("user_id") else None,
    )
    db.add(write)
    db.commit()

    if not gate_result["passed"]:
        write.status = "failed"
        write.erp_response = {"error": f"Gates failed: {', '.join(gate_result['failed'])}", "retry_class": "permanent"}
        db.commit()
        db.refresh(write)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Write gates failed", "gates": gate_result["gates"], "write_id": str(write.write_id)},
        )

    write = _attempt_erp_write(db, write, connection)
    if write.status != "acknowledged":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "ERP did not acknowledge the write", "write_id": str(write.write_id),
                    "erp_response": write.erp_response},
        )
    return _write_out(write)


@router.post("/tenants/{tenant_id}/po-writes/{write_id}/retry", response_model=POWriteOut)
def retry_po_write(
    tenant_id: str,
    write_id: str,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(WRITE_PERMISSION)),
):
    """Re-attempt a failed write with the SAME idempotency key."""
    _check_tenant(ctx, tenant_id)
    write = db.query(Models.PurchaseOrderWrite).filter(
        Models.PurchaseOrderWrite.write_id == write_id,
        Models.PurchaseOrderWrite.tenant_id == tenant_id,
    ).first()
    if not write:
        raise HTTPException(status_code=404, detail="Write not found")
    if write.status == "acknowledged":
        return _write_out(write)  # already done — idempotent no-op

    retry_class = (write.erp_response or {}).get("retry_class")
    if retry_class == "permanent":
        raise HTTPException(status_code=409, detail="Permanent failure — fix the payload, do not retry")

    connection = db.query(Models.TenantConnection).filter(
        Models.TenantConnection.connection_id == write.connection_id,
    ).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    write = _attempt_erp_write(db, write, connection)
    return _write_out(write)


@router.get("/tenants/{tenant_id}/po-writes", response_model=List[POWriteOut])
def list_po_writes(
    tenant_id: str,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    ctx=Depends(check_user_authorization(WRITE_PERMISSION)),
):
    """Audit trail of governed writes for a tenant."""
    _check_tenant(ctx, tenant_id)
    query = db.query(Models.PurchaseOrderWrite).filter(
        Models.PurchaseOrderWrite.tenant_id == tenant_id,
    )
    if status_filter:
        query = query.filter(Models.PurchaseOrderWrite.status == status_filter)
    writes = query.order_by(Models.PurchaseOrderWrite.created_at.desc()).limit(200).all()
    return [_write_out(w) for w in writes]
