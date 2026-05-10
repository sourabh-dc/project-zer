"""
protocol_handlers.py
--------------------
Multi-protocol dispatch for sending purchase orders to vendors.

Supported protocols:
  - api:   REST/JSON POST to vendor endpoint
  - cxml:  cXML OrderRequest document via HTTP POST
  - edi:   EDI 850 Purchase Order (generate + transmit)
  - email: Formatted PO email via notification dispatcher

Each handler returns a DispatchResult dataclass.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import textwrap
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx

from procurement_service.core.helpers.cxml_parser import parse_cxml_response

from procurement_service.utils.logger import logger


@dataclass
class DispatchResult:
    success: bool
    protocol: str
    vendor_id: str
    po_id: str
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    dispatched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "protocol": self.protocol,
            "vendor_id": self.vendor_id,
            "po_id": self.po_id,
            "response_status": self.response_status,
            "error": self.error,
            "dispatched_at": self.dispatched_at.isoformat(),
        }


# =============================================================================
# API (REST/JSON) handler
# =============================================================================

async def dispatch_api(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    timeout: float = 15.0,
) -> DispatchResult:
    """POST JSON payload to vendor's API endpoint."""
    url = getattr(vendor, "api_endpoint_url", None)
    if not url:
        return DispatchResult(
            success=False, protocol="api", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error="No api_endpoint_url configured",
        )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    auth_type = getattr(vendor, "api_auth_type", None) or "none"
    creds = getattr(vendor, "api_auth_credentials", None) or {}

    if auth_type == "bearer" and creds.get("token"):
        headers["Authorization"] = f"Bearer {creds['token']}"
    elif auth_type == "api_key" and creds.get("header") and creds.get("key"):
        headers[creds["header"]] = creds["key"]
    elif auth_type == "hmac" and creds.get("secret"):
        body_bytes = json.dumps(payload, sort_keys=True).encode()
        sig = hmac.new(creds["secret"].encode(), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Signature"] = sig

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        return DispatchResult(
            success=200 <= resp.status_code < 300,
            protocol="api",
            vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""),
            response_status=resp.status_code,
            response_body=resp.text[:2000],
        )
    except Exception as exc:
        logger.error(f"API dispatch to {url} failed: {exc}")
        return DispatchResult(
            success=False, protocol="api", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error=str(exc),
        )


# =============================================================================
# cXML handler
# =============================================================================

def build_cxml_order_request(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    buyer_domain: str = "ZeroQue",
) -> str:
    """Build a cXML OrderRequest document from the dispatch payload."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    payload_id = f"{payload.get('po_number', '')}@{buyer_domain}"

    from_identity = getattr(vendor, "cxml_from_identity", buyer_domain) or buyer_domain
    to_identity = getattr(vendor, "cxml_to_identity", vendor.name) or vendor.name
    shared_secret = getattr(vendor, "cxml_shared_secret", "") or ""

    # Build XML tree
    root = Element("cXML", {
        "payloadID": payload_id,
        "timestamp": timestamp,
        "xml:lang": "en-US",
    })

    # Header
    header = SubElement(root, "Header")

    from_el = SubElement(header, "From")
    from_cred = SubElement(from_el, "Credential", domain=buyer_domain)
    SubElement(from_cred, "Identity").text = from_identity

    to_el = SubElement(header, "To")
    to_cred = SubElement(to_el, "Credential", domain="NetworkId")
    SubElement(to_cred, "Identity").text = to_identity

    sender_el = SubElement(header, "Sender")
    sender_cred = SubElement(sender_el, "Credential", domain=buyer_domain)
    SubElement(sender_cred, "Identity").text = from_identity
    SubElement(sender_cred, "SharedSecret").text = shared_secret
    SubElement(sender_el, "UserAgent").text = "ZeroQue Procurement/1.0"

    # Request > OrderRequest
    request = SubElement(root, "Request")
    order_req = SubElement(request, "OrderRequest")
    order_header = SubElement(order_req, "OrderRequestHeader", {
        "orderID": payload.get("po_number", ""),
        "orderDate": timestamp,
        "type": "new",
    })

    ship_to = payload.get("ship_to", {})
    ship_to_el = SubElement(order_header, "ShipTo")
    addr = SubElement(ship_to_el, "Address")
    SubElement(addr, "Name", **{"xml:lang": "en"}).text = ship_to.get("name", "")
    postal = SubElement(addr, "PostalAddress")
    SubElement(postal, "Street").text = ship_to.get("street", "")
    SubElement(postal, "City").text = ship_to.get("city", "")
    SubElement(postal, "PostalCode").text = ship_to.get("postal_code", "")
    SubElement(postal, "Country", isoCountryCode=ship_to.get("country_code", "GB")).text = ship_to.get("country", "")

    # ItemOut lines
    for idx, line in enumerate(payload.get("lines", []), start=1):
        item_out = SubElement(order_req, "ItemOut", {
            "quantity": str(line.get("quantity", 0)),
            "lineNumber": str(idx),
        })
        item_id = SubElement(item_out, "ItemID")
        SubElement(item_id, "SupplierPartID").text = line.get("sku", "")
        SubElement(item_id, "SupplierPartAuxiliaryID").text = line.get("description", "")

        unit_price = SubElement(item_out, "UnitPrice")
        money = SubElement(unit_price, "Money", currency=payload.get("currency", "GBP"))
        # Convert minor units to major
        price_major = line.get("unit_price_minor", 0) / 100
        money.text = f"{price_major:.2f}"

    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.060/cXML.dtd">\n{xml_bytes}'


async def dispatch_cxml(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    timeout: float = 20.0,
) -> DispatchResult:
    """Send a cXML OrderRequest to the vendor's cXML endpoint."""
    url = getattr(vendor, "cxml_endpoint_url", None)
    if not url:
        return DispatchResult(
            success=False, protocol="cxml", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error="No cxml_endpoint_url configured",
        )

    try:
        cxml_doc = build_cxml_order_request(vendor, payload)
    except Exception as exc:
        logger.error(f"cXML build failed: {exc}")
        return DispatchResult(
            success=False, protocol="cxml", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error=f"cXML build error: {exc}",
        )

    headers = {"Content-Type": "text/xml; charset=utf-8"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, content=cxml_doc, headers=headers)

        response_body = resp.text[:2000]
        status_code = None
        status_text = None
        if resp.text:
            parsed = parse_cxml_response(resp.text)
            if parsed.success and parsed.status_code:
                status_code = parsed.status_code
                status_text = parsed.status_text
                response_body = f"cXML Response {status_code} {status_text or ''}".strip()

        if resp.status_code != 200:
            success = False
        elif status_code is None:
            success = "200" in resp.text[:500]
        else:
            try:
                success = int(status_code) < 300
            except ValueError:
                success = status_code.startswith("2")

        return DispatchResult(
            success=success,
            protocol="cxml",
            vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""),
            response_status=resp.status_code,
            response_body=response_body,
        )
    except Exception as exc:
        logger.error(f"cXML dispatch to {url} failed: {exc}")
        return DispatchResult(
            success=False, protocol="cxml", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error=str(exc),
        )


# =============================================================================
# EDI 850 handler
# =============================================================================

def build_edi_850(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    sender_id: str = "ZEROQUE",
    sender_qualifier: str = "ZZ",
) -> str:
    """Generate an EDI X12 850 Purchase Order document."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%y%m%d")
    time_str = now.strftime("%H%M")
    control_num = str(abs(hash(payload.get("po_id", ""))) % 999999999).zfill(9)

    receiver_id = (getattr(vendor, "edi_partner_id", "") or "").ljust(15)
    receiver_qual = getattr(vendor, "edi_interchange_qualifier", "ZZ") or "ZZ"

    ship_to = payload.get("ship_to", {})
    lines = payload.get("lines", [])

    segments = []

    # ISA - Interchange Control Header
    segments.append(
        f"ISA*00*          *00*          "
        f"*{sender_qualifier}*{sender_id.ljust(15)}"
        f"*{receiver_qual}*{receiver_id}"
        f"*{date_str}*{time_str}*U*00401*{control_num}*0*P*>~"
    )

    # GS - Functional Group Header
    segments.append(
        f"GS*PO*{sender_id}*{(getattr(vendor, 'edi_partner_id', '') or '').strip()}"
        f"*{now.strftime('%Y%m%d')}*{time_str}*{control_num}*X*004010~"
    )

    # ST - Transaction Set Header
    segments.append(f"ST*850*{control_num[:4]}~")

    # BEG - Beginning Segment for PO
    segments.append(
        f"BEG*00*NE*{payload.get('po_number', '')}**{now.strftime('%Y%m%d')}~"
    )

    # N1 - Ship-To Name
    segments.append(f"N1*ST*{ship_to.get('name', '')}~")
    segments.append(f"N3*{ship_to.get('street', '')}~")
    segments.append(
        f"N4*{ship_to.get('city', '')}*{ship_to.get('state', '')}*{ship_to.get('postal_code', '')}*{ship_to.get('country_code', 'GB')}~"
    )

    # PO1 - Line items
    for idx, line in enumerate(lines, start=1):
        price = line.get("unit_price_minor", 0) / 100
        segments.append(
            f"PO1*{idx}*{line.get('quantity', 0)}*EA*{price:.2f}**VP*{line.get('sku', '')}~"
        )
        if line.get("description"):
            segments.append(f"PID*F****{line['description'][:80]}~")

    # CTT - Transaction Totals
    segments.append(f"CTT*{len(lines)}~")

    # SE - Transaction Set Trailer
    seg_count = len(segments) - 2 + 1  # exclude ISA, GS; include SE itself
    segments.append(f"SE*{seg_count}*{control_num[:4]}~")

    # GE - Functional Group Trailer
    segments.append(f"GE*1*{control_num}~")

    # IEA - Interchange Control Trailer
    segments.append(f"IEA*1*{control_num}~")

    return "\n".join(segments)


async def dispatch_edi(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    timeout: float = 20.0,
) -> DispatchResult:
    """
    Generate an EDI 850 document and transmit it.

    Supports EDI-over-API/VAN, AS2 (HTTP), and SFTP drop transports.
    """
    try:
        edi_doc = build_edi_850(vendor, payload)
    except Exception as exc:
        logger.error(f"EDI 850 build failed: {exc}")
        return DispatchResult(
            success=False, protocol="edi", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error=f"EDI build error: {exc}",
        )

    edi_protocol = getattr(vendor, "edi_protocol", "api") or "api"
    edi_config = getattr(vendor, "edi_connection_config", None) or {}

    if edi_protocol in ("api", "van"):
        # Transmit via HTTP POST (EDI VAN gateway or direct API)
        url = edi_config.get("url") or edi_config.get("endpoint")
        if not url:
            return DispatchResult(
                success=False, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
                error="No EDI endpoint URL in edi_connection_config",
            )
        headers = {"Content-Type": "application/edi-x12"}
        if edi_config.get("auth_header") and edi_config.get("auth_token"):
            headers[edi_config["auth_header"]] = edi_config["auth_token"]

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, content=edi_doc, headers=headers)
            return DispatchResult(
                success=200 <= resp.status_code < 300,
                protocol="edi",
                vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
                response_status=resp.status_code,
                response_body=resp.text[:2000],
            )
        except Exception as exc:
            logger.error(f"EDI dispatch failed: {exc}")
            return DispatchResult(
                success=False, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""), error=str(exc),
            )

    if edi_protocol == "as2":
        url = edi_config.get("url") or edi_config.get("endpoint")
        if not url:
            return DispatchResult(
                success=False, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
                error="No AS2 endpoint URL in edi_connection_config",
            )

        headers = {
            "Content-Type": "application/edi-x12",
            "AS2-From": edi_config.get("as2_from", "ZEROQUE"),
            "AS2-To": edi_config.get("as2_to", getattr(vendor, "edi_partner_id", "PARTNER") or "PARTNER"),
            "Subject": edi_config.get("subject", "EDI 850 Purchase Order"),
            "Message-ID": f"<{uuid.uuid4()}@zeroque.local>",
        }
        if edi_config.get("auth_header") and edi_config.get("auth_token"):
            headers[edi_config["auth_header"]] = edi_config["auth_token"]

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, content=edi_doc, headers=headers)
            return DispatchResult(
                success=200 <= resp.status_code < 300,
                protocol="edi",
                vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
                response_status=resp.status_code,
                response_body=resp.text[:2000],
            )
        except Exception as exc:
            logger.error(f"EDI AS2 dispatch failed: {exc}")
            return DispatchResult(
                success=False, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""), error=str(exc),
            )

    if edi_protocol == "sftp":
        outbound_dir = edi_config.get("outbound_dir") or edi_config.get("drop_dir")
        if not outbound_dir:
            return DispatchResult(
                success=False, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
                error="No outbound_dir configured for SFTP transport",
            )
        try:
            os.makedirs(outbound_dir, exist_ok=True)
            filename = f"edi_850_{payload.get('po_number', payload.get('po_id', 'po'))}_{uuid.uuid4().hex}.edi"
            file_path = os.path.join(outbound_dir, filename)
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(edi_doc)
            return DispatchResult(
                success=True, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
                response_body=f"EDI 850 dropped to {file_path}",
            )
        except Exception as exc:
            logger.error(f"EDI SFTP drop failed: {exc}")
            return DispatchResult(
                success=False, protocol="edi", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""), error=str(exc),
            )

    logger.warning(f"EDI protocol '{edi_protocol}' not implemented; document generated but not transmitted")
    return DispatchResult(
        success=True, protocol="edi", vendor_id=vendor.vendor_id,
        po_id=payload.get("po_id", ""),
        response_body=f"EDI 850 generated ({len(edi_doc)} bytes), transport={edi_protocol} pending",
    )


# =============================================================================
# Email handler
# =============================================================================

async def dispatch_email(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    notification_dispatcher=None,
) -> DispatchResult:
    """
    Send a PO notification email to the vendor's notification_email.

    Uses the procurement service's notification dispatcher if available,
    otherwise records for outbox-based delivery.
    """
    email_addr = getattr(vendor, "notification_email", None) or getattr(vendor, "primary_email", None)
    if not email_addr:
        return DispatchResult(
            success=False, protocol="email", vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""), error="No email address configured for vendor",
        )

    lines_text = ""
    for line in payload.get("lines", []):
        price = line.get("unit_price_minor", 0) / 100
        lines_text += f"  - {line.get('sku', 'N/A')} | {line.get('description', '')} | Qty: {line.get('quantity', 0)} | {payload.get('currency', 'GBP')} {price:.2f}\n"

    ship_to = payload.get("ship_to", {})
    email_body = textwrap.dedent(f"""\
        Purchase Order: {payload.get('po_number', 'N/A')}

        Ship To:
          {ship_to.get('name', '')}
          {ship_to.get('street', '')}
          {ship_to.get('city', '')}, {ship_to.get('postal_code', '')}
          {ship_to.get('country', '')}

        Items:
        {lines_text}
        Note: {payload.get('note', 'N/A')}

        Please acknowledge this order.
    """)

    if notification_dispatcher:
        try:
            await notification_dispatcher.send_email(
                to=email_addr,
                subject=f"Purchase Order {payload.get('po_number', '')}",
                body=email_body,
            )
            return DispatchResult(
                success=True, protocol="email", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""),
            )
        except Exception as exc:
            logger.error(f"Email dispatch failed: {exc}")
            return DispatchResult(
                success=False, protocol="email", vendor_id=vendor.vendor_id,
                po_id=payload.get("po_id", ""), error=str(exc),
            )

    # No dispatcher — record for outbox delivery
    logger.info(f"Email PO {payload.get('po_number', '')} queued for {email_addr}")
    return DispatchResult(
        success=True, protocol="email", vendor_id=vendor.vendor_id,
        po_id=payload.get("po_id", ""),
        response_body=f"Queued for delivery to {email_addr}",
    )


# =============================================================================
# Dispatcher router — picks protocol and calls the right handler
# =============================================================================

PROTOCOL_HANDLERS = {
    "api": dispatch_api,
    "cxml": dispatch_cxml,
    "edi": dispatch_edi,
    "email": dispatch_email,
}


async def dispatch_to_vendor(
    vendor: Any,
    payload: Dict[str, Any],
    *,
    protocol_override: Optional[str] = None,
    notification_dispatcher=None,
) -> DispatchResult:
    """
    Route a PO dispatch to the correct protocol handler based on
    vendor.preferred_protocol (or an explicit override).
    """
    protocol = protocol_override or getattr(vendor, "preferred_protocol", "email") or "email"

    handler = PROTOCOL_HANDLERS.get(protocol)
    if not handler:
        return DispatchResult(
            success=False, protocol=protocol, vendor_id=vendor.vendor_id,
            po_id=payload.get("po_id", ""),
            error=f"Unsupported protocol: {protocol}",
        )

    if protocol == "email":
        return await handler(vendor, payload, notification_dispatcher=notification_dispatcher)
    return await handler(vendor, payload)
