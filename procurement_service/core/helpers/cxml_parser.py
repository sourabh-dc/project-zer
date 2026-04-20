"""
cxml_parser.py
--------------
Utilities for parsing inbound cXML documents from vendors.

Handles:
  - cXML ConfirmationRequest  (PO acknowledgement)
  - cXML ShipNoticeRequest    (ASN / shipment notification)
  - cXML StatusUpdateRequest  (order status changes)
  - cXML Response parsing     (result of our OrderRequest)

All parsers return plain dicts suitable for processing by the procurement engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, fromstring

from procurement_service.utils.logger import logger


@dataclass
class CXMLParseResult:
    """Result of parsing a cXML document."""
    document_type: str
    payload_id: Optional[str] = None
    timestamp: Optional[str] = None
    status_code: Optional[str] = None
    status_text: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    raw_xml: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def _get_text(el: Optional[Element], default: str = "") -> str:
    if el is not None and el.text:
        return el.text.strip()
    return default


def _find_recursive(root: Element, tag: str) -> Optional[Element]:
    """Find an element by local name, ignoring namespace prefixes."""
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == tag:
            return el
    return None


def _find_all_recursive(root: Element, tag: str) -> List[Element]:
    """Find all elements by local name."""
    results = []
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == tag:
            results.append(el)
    return results


# =============================================================================
# RESPONSE PARSER (reply to our OrderRequest)
# =============================================================================

def parse_cxml_response(xml_str: str) -> CXMLParseResult:
    """
    Parse a cXML Response document (typically the reply to an OrderRequest).

    Expected structure:
      <cXML>
        <Response>
          <Status code="200" text="OK"/>
        </Response>
      </cXML>
    """
    result = CXMLParseResult(document_type="Response", raw_xml=xml_str)
    try:
        root = fromstring(xml_str)
        result.payload_id = root.get("payloadID")
        result.timestamp = root.get("timestamp")

        status_el = _find_recursive(root, "Status")
        if status_el is not None:
            result.status_code = status_el.get("code")
            result.status_text = status_el.get("text") or _get_text(status_el)

        result.data = {
            "status_code": result.status_code,
            "status_text": result.status_text,
        }
    except Exception as exc:
        result.errors.append(f"XML parse error: {exc}")
        logger.error(f"cXML Response parse failed: {exc}")

    return result


# =============================================================================
# CONFIRMATION REQUEST PARSER (PO Acknowledgement)
# =============================================================================

def parse_cxml_confirmation(xml_str: str) -> CXMLParseResult:
    """
    Parse a cXML ConfirmationRequest (vendor's PO acknowledgement).

    Key data extracted:
      - confirmID, orderID, noticeDate
      - Per-line: lineNumber, quantity, status (accept/reject/backorder)
    """
    result = CXMLParseResult(document_type="ConfirmationRequest", raw_xml=xml_str)
    try:
        root = fromstring(xml_str)
        result.payload_id = root.get("payloadID")
        result.timestamp = root.get("timestamp")

        confirm_header = _find_recursive(root, "ConfirmationHeader")
        if confirm_header is not None:
            result.data["confirm_id"] = confirm_header.get("confirmID")
            result.data["order_id"] = confirm_header.get("orderID")
            result.data["notice_date"] = confirm_header.get("noticeDate")
            result.data["type"] = confirm_header.get("type", "accept")
            result.data["operation"] = confirm_header.get("operation", "new")

        # Parse confirmed lines
        confirmed_lines = []
        for item_in in _find_all_recursive(root, "ConfirmationItem"):
            line = {
                "line_number": item_in.get("lineNumber"),
                "quantity": item_in.get("quantity"),
            }

            status_el = _find_recursive(item_in, "ConfirmationStatus")
            if status_el is not None:
                line["status"] = status_el.get("type", "accept")
                line["quantity_confirmed"] = status_el.get("quantity")
                line["delivery_date"] = status_el.get("deliveryDate")

            unit_price = _find_recursive(item_in, "UnitPrice")
            if unit_price is not None:
                money = _find_recursive(unit_price, "Money")
                if money is not None:
                    line["unit_price"] = _get_text(money)
                    line["currency"] = money.get("currency")

            confirmed_lines.append(line)

        result.data["lines"] = confirmed_lines

    except Exception as exc:
        result.errors.append(f"XML parse error: {exc}")
        logger.error(f"cXML ConfirmationRequest parse failed: {exc}")

    return result


# =============================================================================
# SHIP NOTICE PARSER (ASN)
# =============================================================================

def parse_cxml_ship_notice(xml_str: str) -> CXMLParseResult:
    """
    Parse a cXML ShipNoticeRequest (Advanced Shipping Notice from vendor).

    Key data extracted:
      - shipmentID, noticeDate, deliveryDate
      - Carrier / tracking info
      - Per-line: lineNumber, quantity, itemID
    """
    result = CXMLParseResult(document_type="ShipNoticeRequest", raw_xml=xml_str)
    try:
        root = fromstring(xml_str)
        result.payload_id = root.get("payloadID")
        result.timestamp = root.get("timestamp")

        header = _find_recursive(root, "ShipNoticeHeader")
        if header is not None:
            result.data["shipment_id"] = header.get("shipmentID")
            result.data["notice_date"] = header.get("noticeDate")
            result.data["delivery_date"] = header.get("deliveryDate")
            result.data["order_id"] = header.get("orderID")

        # Carrier / tracking
        carrier_el = _find_recursive(root, "CarrierIdentifier")
        if carrier_el is not None:
            result.data["carrier"] = _get_text(carrier_el)
            result.data["carrier_domain"] = carrier_el.get("domain")

        tracking_el = _find_recursive(root, "ShipmentIdentifier")
        if tracking_el is not None:
            result.data["tracking_number"] = _get_text(tracking_el)

        # Line items
        shipped_lines = []
        for item in _find_all_recursive(root, "ShipNoticeItem"):
            line = {
                "line_number": item.get("lineNumber"),
                "quantity": item.get("quantity"),
            }
            item_id = _find_recursive(item, "SupplierPartID")
            if item_id is not None:
                line["sku"] = _get_text(item_id)
            shipped_lines.append(line)

        result.data["lines"] = shipped_lines

    except Exception as exc:
        result.errors.append(f"XML parse error: {exc}")
        logger.error(f"cXML ShipNoticeRequest parse failed: {exc}")

    return result


# =============================================================================
# STATUS UPDATE PARSER
# =============================================================================

def parse_cxml_status_update(xml_str: str) -> CXMLParseResult:
    """Parse a generic cXML StatusUpdateRequest."""
    result = CXMLParseResult(document_type="StatusUpdateRequest", raw_xml=xml_str)
    try:
        root = fromstring(xml_str)
        result.payload_id = root.get("payloadID")
        result.timestamp = root.get("timestamp")

        status_el = _find_recursive(root, "Status")
        if status_el is not None:
            result.status_code = status_el.get("code")
            result.status_text = status_el.get("text") or _get_text(status_el)

        result.data["status_code"] = result.status_code
        result.data["status_text"] = result.status_text

    except Exception as exc:
        result.errors.append(f"XML parse error: {exc}")

    return result


# =============================================================================
# AUTO-DETECT AND PARSE
# =============================================================================

def parse_cxml(xml_str: str) -> CXMLParseResult:
    """
    Auto-detect the cXML document type and parse accordingly.

    Looks for key elements:
      - ConfirmationRequest → parse_cxml_confirmation
      - ShipNoticeRequest   → parse_cxml_ship_notice
      - StatusUpdateRequest → parse_cxml_status_update
      - Response            → parse_cxml_response
    """
    try:
        root = fromstring(xml_str)
    except Exception as exc:
        return CXMLParseResult(
            document_type="unknown",
            errors=[f"Invalid XML: {exc}"],
            raw_xml=xml_str,
        )

    if _find_recursive(root, "ConfirmationRequest") is not None:
        return parse_cxml_confirmation(xml_str)
    if _find_recursive(root, "ShipNoticeRequest") is not None:
        return parse_cxml_ship_notice(xml_str)
    if _find_recursive(root, "StatusUpdateRequest") is not None:
        return parse_cxml_status_update(xml_str)
    if _find_recursive(root, "Response") is not None:
        return parse_cxml_response(xml_str)

    return CXMLParseResult(
        document_type="unknown",
        errors=["Unrecognized cXML document type"],
        raw_xml=xml_str,
    )
