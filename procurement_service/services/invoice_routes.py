from typing import Optional
from io import StringIO
import csv

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response

from procurement_service.Schemas import InvoiceCreate
from procurement_service.core.helpers.serializers import invoice_dict, sla_dict
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization


router = APIRouter(tags=["invoices"])


@router.post("/purchase-orders/{po_id}/invoices")
async def create_invoice(
    po_id: str,
    payload: InvoiceCreate,
    x_idempotency_key: Optional[str] = Header(default=None),
    ctx=Depends(check_user_authorization("invoices.create")),
    policy=Depends(require_policy("invoice.create")),
):
    container = get_container()
    with container.lock:
        cached = container.get_idempotent_response(ctx.tenant_id, f"POST:/purchase-orders/{po_id}/invoices", x_idempotency_key)
        if cached:
            return cached

        po = container.platform.store.purchase_orders.get(po_id)
        if not po or po.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "purchase order not found")

        invoice = container.platform.create_invoice(
            tenant_id=ctx.tenant_id,
            po_id=po_id,
            invoice_number=payload.invoice_number,
            lines=[line.model_dump() for line in payload.lines],
        )
        response = invoice_dict(container.platform, invoice)
        container.save_idempotent_response(ctx.tenant_id, f"POST:/purchase-orders/{po_id}/invoices", x_idempotency_key, response)
        return response


@router.get("/purchase-orders/{po_id}/slas")
async def list_po_slas(
    po_id: str,
    ctx=Depends(check_user_authorization("slas.view")),
    policy=Depends(require_policy("purchase_order.read")),
):
    container = get_container()
    po = container.platform.store.purchase_orders.get(po_id)
    if not po or po.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "purchase order not found")
    slas = [
        sla_dict(item)
        for item in container.platform.store.sla_records.values()
        if item.entity_id == po_id and item.tenant_id == ctx.tenant_id
    ]
    return {"items": slas}


@router.get("/orders/{order_id}/invoices")
async def list_order_invoices(
    order_id: str,
    ctx=Depends(check_user_authorization("invoices.view")),
    policy=Depends(require_policy("invoice.read")),
):
    container = get_container()
    order = container.platform.store.orders.get(order_id)
    if not order or order.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "order not found")

    po_ids = set(order.po_ids)
    items = [
        invoice_dict(container.platform, invoice)
        for invoice in container.platform.store.invoices.values()
        if invoice.tenant_id == ctx.tenant_id and invoice.po_id in po_ids
    ]
    return {"items": items}


@router.get("/invoices/{invoice_id}")
async def get_invoice(
    invoice_id: str,
    ctx=Depends(check_user_authorization("invoices.view")),
    policy=Depends(require_policy("invoice.read")),
):
    container = get_container()
    invoice = container.platform.store.invoices.get(invoice_id)
    if not invoice or invoice.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "invoice not found")
    return invoice_dict(container.platform, invoice)


@router.get("/invoices/{invoice_id}/download")
async def download_invoice(
    invoice_id: str,
    ctx=Depends(check_user_authorization("invoices.view")),
    policy=Depends(require_policy("invoice.read")),
):
    container = get_container()
    invoice = container.platform.store.invoices.get(invoice_id)
    if not invoice or invoice.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "invoice not found")

    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["invoice_number", "po_id", "invoice_line_id", "po_line_id", "billed_quantity", "billed_unit_price_minor", "match_status"])
    for line_id in invoice.line_ids:
        line = container.platform.store.invoice_lines[line_id]
        writer.writerow(
            [
                invoice.invoice_number,
                invoice.po_id,
                line.invoice_line_id,
                line.po_line_id,
                line.billed_quantity,
                line.billed_unit_price_minor,
                line.match_status,
            ]
        )

    csv_bytes = stream.getvalue().encode("utf-8")
    filename = f"invoice_{invoice.invoice_number}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
