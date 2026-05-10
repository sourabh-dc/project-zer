"""
vendor_integration_routes.py
----------------------------
API endpoints for vendor integration management and order fulfillment dispatch.

Endpoints:
  PUT  /vendors/{vendor_id}/integration     — Configure vendor integration (protocol, endpoints)
  GET  /vendors/{vendor_id}/integration     — Get vendor integration config
  PUT  /vendors/{vendor_id}/onboarding      — Update vendor onboarding metadata
  POST /vendors/{vendor_id}/dispatch-po     — Dispatch a PO to vendor via configured protocol
  POST /vendors/{vendor_id}/fulfillment     — Vendor-facing: update fulfillment status
  POST /vendors/{vendor_id}/webhook/test    — Test webhook connectivity
"""

import hashlib
import hmac
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request

from procurement_service.Schemas import (
    VendorIntegrationConfig,
    VendorOnboardingUpdate,
    VendorFulfillmentUpdate,
    OrderDispatchPayload,
)
from procurement_service.core.helpers.serializers import vendor_integration_dict
from procurement_service.core.helpers.protocol_handlers import (
    dispatch_to_vendor,
    build_cxml_order_request,
    build_edi_850,
)
from procurement_service.core.helpers.cxml_parser import parse_cxml
from procurement_service.core.helpers.edi_parser import parse_edi
from procurement_service.core.policy_client import require_policy
from procurement_service.core.runtime import get_container
from procurement_service.core.user_auth import check_user_authorization
from procurement_service.utils.logger import logger


router = APIRouter(tags=["vendor-integration"])


def _find_vendor_po(container, *, vendor_id: str, tenant_id: str, po_number: Optional[str] = None) -> Optional[object]:
    if not po_number:
        return None
    for po in container.platform.store.purchase_orders.values():
        if po.vendor_id == vendor_id and po.tenant_id == tenant_id and po.po_number == po_number:
            return po
    return None


def _match_po_line_id(container, po, *, line_number: Optional[str] = None, sku: Optional[str] = None) -> Optional[str]:
    if line_number and str(line_number).isdigit():
        index = int(line_number)
        if 1 <= index <= len(po.line_ids):
            return po.line_ids[index - 1]

    if sku:
        for line_id in po.line_ids:
            line = container.platform.store.po_lines[line_id]
            if line.sku == sku:
                return line_id
    return None


def _to_minor(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(Decimal(str(value)) * 100)
    except (InvalidOperation, ValueError):
        return None


def _verify_webhook_signature(secret: Optional[str], body: bytes, signature: Optional[str]) -> bool:
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _apply_cxml_result(container, *, vendor_id: str, tenant_id: str, result) -> None:
    if result.document_type == "ConfirmationRequest":
        po_number = result.data.get("order_id")
        po = _find_vendor_po(container, vendor_id=vendor_id, tenant_id=tenant_id, po_number=po_number)
        if not po:
            raise HTTPException(404, "Purchase order not found for confirmation")

        decisions = []
        errors = []
        for line in result.data.get("lines", []):
            po_line_id = _match_po_line_id(container, po, line_number=line.get("line_number"))
            if not po_line_id:
                errors.append(f"No PO line match for line_number={line.get('line_number')}")
                continue

            status_raw = (line.get("status") or "accept").lower()
            if status_raw in ("accept", "accepted"):
                status = "accepted"
            elif status_raw in ("reject", "rejected"):
                status = "rejected"
            else:
                status = "accepted_with_changes"

            qty = line.get("quantity_confirmed") or line.get("quantity") or 0
            decisions.append(
                {
                    "po_line_id": po_line_id,
                    "accepted_quantity": int(qty),
                    "proposed_unit_price_minor": _to_minor(line.get("unit_price")),
                    "status": status,
                    "reason": "cxml_confirmation",
                }
            )

        if errors:
            raise HTTPException(422, {"errors": errors, "document_type": result.document_type})

        container.platform.vendor_acknowledge(po.po_id, decisions)

    elif result.document_type == "ShipNoticeRequest":
        po_number = result.data.get("order_id")
        po = _find_vendor_po(container, vendor_id=vendor_id, tenant_id=tenant_id, po_number=po_number)
        if not po:
            raise HTTPException(404, "Purchase order not found for ship notice")

        tracking_number = result.data.get("tracking_number") or result.data.get("shipment_id")
        if not tracking_number:
            raise HTTPException(422, "Ship notice missing tracking number")

        shipment_lines = []
        errors = []
        for line in result.data.get("lines", []):
            po_line_id = _match_po_line_id(container, po, line_number=line.get("line_number"), sku=line.get("sku"))
            if not po_line_id:
                errors.append(f"No PO line match for line_number={line.get('line_number')}")
                continue
            shipment_lines.append(
                {
                    "po_line_id": po_line_id,
                    "quantity": int(line.get("quantity") or 0),
                }
            )

        if errors:
            raise HTTPException(422, {"errors": errors, "document_type": result.document_type})

        container.platform.create_shipment(po.po_id, tracking_number, shipment_lines)


# =============================================================================
# INTEGRATION CONFIGURATION
# =============================================================================

@router.put("/vendors/{vendor_id}/integration")
async def configure_vendor_integration(
    vendor_id: str,
    config: VendorIntegrationConfig,
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.update")),
):
    """Configure a vendor's integration protocol and endpoint details."""
    container = get_container()
    with container.lock:
        vendor = container.platform.store.vendors.get(vendor_id)
        if not vendor or vendor.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Vendor not found")

        # Apply integration config
        vendor.preferred_protocol = config.preferred_protocol
        vendor.channel = config.preferred_protocol

        if config.api_endpoint_url is not None:
            vendor.api_endpoint_url = config.api_endpoint_url
        if config.cxml_endpoint_url is not None:
            vendor.cxml_endpoint_url = config.cxml_endpoint_url
        if config.cxml_from_identity is not None:
            vendor.cxml_from_identity = config.cxml_from_identity
        if config.cxml_to_identity is not None:
            vendor.cxml_to_identity = config.cxml_to_identity
        if config.cxml_shared_secret is not None:
            vendor.cxml_shared_secret = config.cxml_shared_secret
        if config.edi_partner_id is not None:
            vendor.edi_partner_id = config.edi_partner_id
        if config.edi_interchange_qualifier is not None:
            vendor.edi_interchange_qualifier = config.edi_interchange_qualifier
        if config.edi_protocol is not None:
            vendor.edi_protocol = config.edi_protocol
        if config.edi_connection_config is not None:
            vendor.edi_connection_config = config.edi_connection_config
        if config.notification_email is not None:
            vendor.notification_email = config.notification_email
        if config.webhook_url is not None:
            vendor.webhook_url = config.webhook_url
        if config.webhook_secret is not None:
            vendor.webhook_secret = config.webhook_secret

        # API auth
        if config.api_auth_type is not None:
            vendor.api_auth_type = config.api_auth_type
        if config.api_auth_header or config.api_auth_token:
            creds = getattr(vendor, "api_auth_credentials", None) or {}
            if config.api_auth_header:
                creds["header"] = config.api_auth_header
            if config.api_auth_token:
                creds["token"] = config.api_auth_token
            vendor.api_auth_credentials = creds

        container.platform.store.emit("vendor.integration_configured", vendor_id)
        logger.info(f"Vendor {vendor_id} integration configured: protocol={config.preferred_protocol}")

    return vendor_integration_dict(vendor)


@router.get("/vendors/{vendor_id}/integration")
async def get_vendor_integration(
    vendor_id: str,
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.read")),
):
    """Get a vendor's integration configuration."""
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")
    return vendor_integration_dict(vendor)


# =============================================================================
# ONBOARDING METADATA
# =============================================================================

@router.put("/vendors/{vendor_id}/onboarding")
async def update_vendor_onboarding(
    vendor_id: str,
    update: VendorOnboardingUpdate,
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.update")),
):
    """Update vendor onboarding metadata (payment terms, lead time, etc.)."""
    container = get_container()
    with container.lock:
        vendor = container.platform.store.vendors.get(vendor_id)
        if not vendor or vendor.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Vendor not found")

        for field_name in (
            "onboarding_status", "payment_terms", "return_policy",
            "lead_time_days", "minimum_order_minor", "tax_id",
            "duns_number", "vendor_metadata",
        ):
            val = getattr(update, field_name, None)
            if val is not None:
                setattr(vendor, field_name, val)

        container.platform.store.emit("vendor.onboarding_updated", vendor_id)
        logger.info(f"Vendor {vendor_id} onboarding updated: status={vendor.onboarding_status}")

    return vendor_integration_dict(vendor)


# =============================================================================
# ORDER DISPATCH (multi-protocol)
# =============================================================================

@router.post("/vendors/{vendor_id}/dispatch-po")
async def dispatch_purchase_order(
    vendor_id: str,
    payload: OrderDispatchPayload,
    protocol_override: Optional[str] = None,
    ctx=Depends(check_user_authorization("orders.manage")),
    policy=Depends(require_policy("order.dispatch")),
):
    """
    Dispatch a purchase order to a vendor using their configured protocol.

    The system will:
      1. Look up the vendor's preferred_protocol (or use protocol_override)
      2. Build the protocol-specific document (JSON, cXML, EDI 850, or email)
      3. Transmit to the vendor's configured endpoint
      4. Return the dispatch result
    """
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")

    dispatch_data = payload.model_dump()

    result = await dispatch_to_vendor(
        vendor,
        dispatch_data,
        protocol_override=protocol_override,
    )

    with container.lock:
        container.platform.store.emit(
            f"po.dispatched.{result.protocol}",
            payload.po_id,
        )
        if result.protocol == "cxml" and result.response_body:
            container.platform.store.emit("po.cxml.response", payload.po_id)

    if not result.success:
        logger.warning(f"PO dispatch failed for vendor {vendor_id}: {result.error}")

    return result.to_dict()


# =============================================================================
# VENDOR-FACING FULFILLMENT UPDATE
# =============================================================================

@router.post("/vendors/{vendor_id}/fulfillment")
async def vendor_fulfillment_update(
    vendor_id: str,
    update: VendorFulfillmentUpdate,
    x_idempotency_key: Optional[str] = Header(default=None),
    ctx=Depends(check_user_authorization("vendors.portal.update")),
    policy=Depends(require_policy("vendor.fulfillment_update")),
):
    """
    Vendor-facing endpoint: update fulfillment status for an order.

    Supports: acknowledged, shipped, partially_shipped, cancelled.
    When shipped/partially_shipped, a Shipment record is created.
    """
    container = get_container()
    with container.lock:
        vendor = container.platform.store.vendors.get(vendor_id)
        if not vendor or vendor.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Vendor not found")

        event_type = f"vendor.fulfillment.{update.status}"
        container.platform.store.emit(event_type, vendor_id)

        # If shipment lines are provided, create a shipment record
        if update.status in ("shipped", "partially_shipped") and update.lines and update.tracking_number:
            # Find the first PO for this vendor
            po = None
            for p in container.platform.store.purchase_orders.values():
                if p.vendor_id == vendor_id and p.tenant_id == ctx.tenant_id and p.status in ("issued", "acknowledged"):
                    po = p
                    break

            if po:
                shipment = container.platform.create_shipment(
                    po.po_id,
                    update.tracking_number,
                    [line.model_dump() for line in update.lines],
                )
                logger.info(f"Shipment {shipment.shipment_id} created from vendor fulfillment update")
                return {
                    "status": update.status,
                    "shipment_id": shipment.shipment_id,
                    "tracking_number": update.tracking_number,
                    "note": update.note,
                }

    return {
        "status": update.status,
        "vendor_id": vendor_id,
        "note": update.note,
    }


# =============================================================================
# WEBHOOK CONNECTIVITY TEST
# =============================================================================

@router.post("/vendors/{vendor_id}/webhook/test")
async def test_vendor_webhook(
    vendor_id: str,
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.update")),
):
    """Send a test ping to the vendor's configured webhook URL."""
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")

    webhook_url = getattr(vendor, "webhook_url", None)
    if not webhook_url:
        raise HTTPException(422, "No webhook URL configured for this vendor")

    import httpx
    import time

    test_payload = {
        "event": "webhook.test",
        "vendor_id": vendor_id,
        "timestamp": time.time(),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=test_payload)
        return {
            "success": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "response_time_ms": int(resp.elapsed.total_seconds() * 1000),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
        }


# =============================================================================
# DOCUMENT PREVIEW (for debugging / onboarding)
# =============================================================================

@router.post("/vendors/{vendor_id}/preview-document")
async def preview_vendor_document(
    vendor_id: str,
    payload: OrderDispatchPayload,
    protocol: str = "cxml",
    ctx=Depends(check_user_authorization("vendors.manage")),
    policy=Depends(require_policy("vendor.read")),
):
    """
    Preview the document that would be sent to a vendor without actually
    dispatching it. Useful for testing cXML/EDI configuration during onboarding.
    """
    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")

    data = payload.model_dump()

    if protocol == "cxml":
        doc = build_cxml_order_request(vendor, data)
        return {"protocol": "cxml", "content_type": "text/xml", "document": doc}
    elif protocol == "edi":
        doc = build_edi_850(vendor, data)
        return {"protocol": "edi", "content_type": "application/edi-x12", "document": doc}
    elif protocol == "api":
        return {"protocol": "api", "content_type": "application/json", "document": data}
    else:
        raise HTTPException(422, f"Unsupported protocol: {protocol}")


# =============================================================================
# INBOUND: cXML from vendor
# =============================================================================

@router.post("/vendors/{vendor_id}/inbound/cxml")
async def receive_vendor_cxml(
    vendor_id: str,
    request: Request,
    ctx=Depends(check_user_authorization("vendors.portal.update")),
    policy=Depends(require_policy("vendor.fulfillment_update")),
):
    """
    Receive an inbound cXML document from a vendor (ConfirmationRequest,
    ShipNoticeRequest, or StatusUpdate).

    The endpoint parses the document, emits an event, and returns the
    parsed result for further processing.
    """
    body = await request.body()
    xml_str = body.decode("utf-8")

    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")

    result = parse_cxml(xml_str)

    with container.lock:
        container.platform.store.emit(
            f"vendor.cxml.{result.document_type.lower()}",
            vendor_id,
        )

    if not result.success:
        logger.warning(f"cXML parse errors from vendor {vendor_id}: {result.errors}")
        raise HTTPException(422, {"errors": result.errors, "document_type": result.document_type})

    _apply_cxml_result(container, vendor_id=vendor_id, tenant_id=ctx.tenant_id, result=result)

    logger.info(f"Received cXML {result.document_type} from vendor {vendor_id}")
    return {
        "document_type": result.document_type,
        "payload_id": result.payload_id,
        "data": result.data,
    }


# =============================================================================
# INBOUND: cXML vendor webhook
# =============================================================================

@router.post("/vendors/{vendor_id}/webhook/cxml")
async def receive_vendor_cxml_webhook(
    vendor_id: str,
    request: Request,
    x_webhook_signature: Optional[str] = Header(default=None),
):
    """
    Vendor callback endpoint for cXML payloads.

    If webhook_secret is configured for the vendor, requests must include
    an X-Webhook-Signature header with an HMAC-SHA256 hex digest of the body.
    """
    body = await request.body()
    xml_str = body.decode("utf-8")

    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found")

    if not _verify_webhook_signature(getattr(vendor, "webhook_secret", None), body, x_webhook_signature):
        raise HTTPException(401, "Invalid webhook signature")

    result = parse_cxml(xml_str)

    with container.lock:
        container.platform.store.emit(
            f"vendor.cxml.{result.document_type.lower()}",
            vendor_id,
        )

    if not result.success:
        logger.warning(f"cXML parse errors from vendor {vendor_id}: {result.errors}")
        raise HTTPException(422, {"errors": result.errors, "document_type": result.document_type})

    _apply_cxml_result(container, vendor_id=vendor_id, tenant_id=vendor.tenant_id, result=result)

    logger.info(f"Received cXML webhook {result.document_type} from vendor {vendor_id}")
    return {
        "document_type": result.document_type,
        "payload_id": result.payload_id,
        "data": result.data,
    }


# =============================================================================
# INBOUND: EDI from vendor
# =============================================================================

@router.post("/vendors/{vendor_id}/inbound/edi")
async def receive_vendor_edi(
    vendor_id: str,
    request: Request,
    ctx=Depends(check_user_authorization("vendors.portal.update")),
    policy=Depends(require_policy("vendor.fulfillment_update")),
):
    """
    Receive an inbound EDI document from a vendor (855, 856, 810, 997).

    The endpoint parses the document, emits an event, and returns the
    parsed result for further processing.
    """
    body = await request.body()
    raw = body.decode("utf-8")

    container = get_container()
    vendor = container.platform.store.vendors.get(vendor_id)
    if not vendor or vendor.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Vendor not found")

    result = parse_edi(raw)

    with container.lock:
        container.platform.store.emit(
            f"vendor.edi.{result.transaction_type}",
            vendor_id,
        )

    if not result.success:
        logger.warning(f"EDI parse errors from vendor {vendor_id}: {result.errors}")
        raise HTTPException(422, {"errors": result.errors, "transaction_type": result.transaction_type})

    if result.transaction_type == "855":
        po_number = result.data.get("po_number")
        po = _find_vendor_po(container, vendor_id=vendor_id, tenant_id=ctx.tenant_id, po_number=po_number)
        if not po:
            raise HTTPException(404, "Purchase order not found for 855")

        decisions = []
        errors = []
        for line in result.data.get("lines", []):
            po_line_id = _match_po_line_id(
                container,
                po,
                line_number=line.get("line_number"),
                sku=line.get("product_id"),
            )
            if not po_line_id:
                errors.append(f"No PO line match for line_number={line.get('line_number')}")
                continue

            ack_status = (line.get("ack_status") or "IA").upper()
            if ack_status == "IA":
                status = "accepted"
            elif ack_status == "IR":
                status = "rejected"
            else:
                status = "accepted_with_changes"

            qty = line.get("quantity_accepted") or line.get("quantity_ordered") or 0
            decisions.append(
                {
                    "po_line_id": po_line_id,
                    "accepted_quantity": int(qty),
                    "proposed_unit_price_minor": _to_minor(line.get("unit_price")),
                    "status": status,
                    "reason": "edi_855",
                }
            )

        if errors:
            raise HTTPException(422, {"errors": errors, "transaction_type": result.transaction_type})

        container.platform.vendor_acknowledge(po.po_id, decisions)

    elif result.transaction_type == "856":
        po_number = result.data.get("po_number")
        po = _find_vendor_po(container, vendor_id=vendor_id, tenant_id=ctx.tenant_id, po_number=po_number)
        if not po:
            raise HTTPException(404, "Purchase order not found for 856")

        tracking_number = result.data.get("tracking_number")
        if not tracking_number:
            raise HTTPException(422, "ASN missing tracking number")

        shipment_lines = []
        errors = []
        for line in result.data.get("shipped_items", []):
            po_line_id = _match_po_line_id(container, po, line_number=line.get("line_number"))
            if not po_line_id:
                errors.append(f"No PO line match for line_number={line.get('line_number')}")
                continue
            shipment_lines.append(
                {
                    "po_line_id": po_line_id,
                    "quantity": int(line.get("quantity_shipped") or 0),
                }
            )

        if errors:
            raise HTTPException(422, {"errors": errors, "transaction_type": result.transaction_type})

        container.platform.create_shipment(po.po_id, tracking_number, shipment_lines)

    elif result.transaction_type == "810":
        po_number = result.data.get("po_number")
        po = _find_vendor_po(container, vendor_id=vendor_id, tenant_id=ctx.tenant_id, po_number=po_number)
        if not po:
            raise HTTPException(404, "Purchase order not found for 810")

        invoice_number = result.data.get("invoice_number") or result.control_number or "EDI-810"
        invoice_lines = []
        errors = []
        for line in result.data.get("lines", []):
            po_line_id = _match_po_line_id(container, po, line_number=line.get("line_number"), sku=line.get("product_id"))
            if not po_line_id:
                errors.append(f"No PO line match for line_number={line.get('line_number')}")
                continue
            qty = int(line.get("quantity_invoiced") or 0)
            unit_price_minor = _to_minor(line.get("unit_price"))
            if unit_price_minor is None:
                errors.append(f"Invalid unit_price for line_number={line.get('line_number')}")
                continue
            invoice_lines.append(
                {
                    "po_line_id": po_line_id,
                    "billed_quantity": qty,
                    "billed_unit_price_minor": unit_price_minor,
                }
            )

        if errors:
            raise HTTPException(422, {"errors": errors, "transaction_type": result.transaction_type})

        container.platform.create_invoice(ctx.tenant_id, po.po_id, invoice_number, invoice_lines)

    logger.info(f"Received EDI {result.transaction_type} from vendor {vendor_id}")
    return {
        "transaction_type": result.transaction_type,
        "control_number": result.control_number,
        "sender_id": result.sender_id,
        "data": result.data,
    }
