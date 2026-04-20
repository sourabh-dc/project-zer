"""
edi_parser.py
-------------
Utilities for parsing inbound EDI X12 documents from vendors.

Handles:
  - 855 Purchase Order Acknowledgment
  - 856 Advance Ship Notice (ASN)
  - 810 Invoice
  - 997 Functional Acknowledgment

All parsers return plain dicts suitable for processing by the procurement engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from procurement_service.utils.logger import logger


@dataclass
class EDIParseResult:
    """Result of parsing an EDI document."""
    transaction_type: str
    control_number: Optional[str] = None
    sender_id: Optional[str] = None
    receiver_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    segments: List[List[str]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def _parse_segments(raw: str) -> List[List[str]]:
    """
    Split raw EDI text into a list of segments, each being a list of elements.
    Handles ~ as segment terminator and * as element separator.
    """
    # Normalize line endings and strip
    raw = raw.replace("\r\n", "\n").replace("\r", "").strip()

    # Detect segment terminator (usually ~ but could be at end of lines)
    if "~" in raw:
        seg_strs = [s.strip() for s in raw.split("~") if s.strip()]
    else:
        seg_strs = [s.strip() for s in raw.split("\n") if s.strip()]

    return [seg.split("*") for seg in seg_strs]


def _find_segments(segments: List[List[str]], segment_id: str) -> List[List[str]]:
    """Find all segments with a given ID (first element)."""
    return [s for s in segments if s and s[0] == segment_id]


def _find_segment(segments: List[List[str]], segment_id: str) -> Optional[List[str]]:
    """Find the first segment with a given ID."""
    matches = _find_segments(segments, segment_id)
    return matches[0] if matches else None


def _safe_get(segment: Optional[List[str]], index: int, default: str = "") -> str:
    """Safely get an element from a segment."""
    if segment and index < len(segment):
        return segment[index]
    return default


# =============================================================================
# ISA / GS HEADER PARSING (common to all transaction types)
# =============================================================================

def _parse_envelope(segments: List[List[str]]) -> Dict[str, Any]:
    """Parse ISA/GS envelope headers."""
    envelope: Dict[str, Any] = {}

    isa = _find_segment(segments, "ISA")
    if isa:
        envelope["sender_qualifier"] = _safe_get(isa, 5)
        envelope["sender_id"] = _safe_get(isa, 6).strip()
        envelope["receiver_qualifier"] = _safe_get(isa, 7)
        envelope["receiver_id"] = _safe_get(isa, 8).strip()
        envelope["date"] = _safe_get(isa, 9)
        envelope["time"] = _safe_get(isa, 10)
        envelope["control_number"] = _safe_get(isa, 13)

    gs = _find_segment(segments, "GS")
    if gs:
        envelope["functional_id"] = _safe_get(gs, 1)
        envelope["app_sender"] = _safe_get(gs, 2)
        envelope["app_receiver"] = _safe_get(gs, 3)
        envelope["group_date"] = _safe_get(gs, 4)
        envelope["group_control"] = _safe_get(gs, 6)

    st = _find_segment(segments, "ST")
    if st:
        envelope["transaction_type"] = _safe_get(st, 1)
        envelope["transaction_control"] = _safe_get(st, 2)

    return envelope


# =============================================================================
# 855 - Purchase Order Acknowledgment
# =============================================================================

def parse_edi_855(raw: str) -> EDIParseResult:
    """
    Parse an EDI 855 Purchase Order Acknowledgment.

    Key segments:
      BAK - Beginning segment (PO number, date, ack type)
      PO1 - Line item acknowledgment
      ACK - Line item status (accepted/rejected/quantity change)
    """
    result = EDIParseResult(transaction_type="855")
    try:
        segments = _parse_segments(raw)
        result.segments = segments
        envelope = _parse_envelope(segments)
        result.control_number = envelope.get("control_number")
        result.sender_id = envelope.get("sender_id")
        result.receiver_id = envelope.get("receiver_id")

        # BAK segment: acknowledgment header
        bak = _find_segment(segments, "BAK")
        if bak:
            result.data["ack_type"] = _safe_get(bak, 1)  # AC=acknowledge, AD=accept with changes, RD=reject
            result.data["po_number"] = _safe_get(bak, 3)
            result.data["po_date"] = _safe_get(bak, 4)

        # PO1 and ACK segments: line-level acknowledgments
        lines = []
        current_line = None
        for seg in segments:
            if seg[0] == "PO1":
                if current_line:
                    lines.append(current_line)
                current_line = {
                    "line_number": _safe_get(seg, 1),
                    "quantity_ordered": _safe_get(seg, 2),
                    "unit": _safe_get(seg, 3),
                    "unit_price": _safe_get(seg, 4),
                    "product_id_qualifier": _safe_get(seg, 6),
                    "product_id": _safe_get(seg, 7),
                }
            elif seg[0] == "ACK" and current_line:
                current_line["ack_status"] = _safe_get(seg, 1)  # IA=accepted, IR=rejected, IC=changed
                current_line["quantity_accepted"] = _safe_get(seg, 2)
                current_line["unit_ack"] = _safe_get(seg, 3)
                current_line["delivery_date"] = _safe_get(seg, 4)

        if current_line:
            lines.append(current_line)

        result.data["lines"] = lines

    except Exception as exc:
        result.errors.append(f"EDI 855 parse error: {exc}")
        logger.error(f"EDI 855 parse failed: {exc}")

    return result


# =============================================================================
# 856 - Advance Ship Notice (ASN)
# =============================================================================

def parse_edi_856(raw: str) -> EDIParseResult:
    """
    Parse an EDI 856 Advance Ship Notice.

    Key segments:
      BSN - Beginning segment (shipment ID, date)
      HL  - Hierarchical level (shipment > order > item)
      TD5 - Carrier details
      REF - Reference numbers (tracking, PO, etc.)
      SN1 - Item detail (shipped quantities)
    """
    result = EDIParseResult(transaction_type="856")
    try:
        segments = _parse_segments(raw)
        result.segments = segments
        envelope = _parse_envelope(segments)
        result.control_number = envelope.get("control_number")
        result.sender_id = envelope.get("sender_id")
        result.receiver_id = envelope.get("receiver_id")

        # BSN segment
        bsn = _find_segment(segments, "BSN")
        if bsn:
            result.data["shipment_id"] = _safe_get(bsn, 2)
            result.data["shipment_date"] = _safe_get(bsn, 3)
            result.data["shipment_time"] = _safe_get(bsn, 4)

        # TD5 - Carrier info
        td5 = _find_segment(segments, "TD5")
        if td5:
            result.data["carrier_code"] = _safe_get(td5, 3)
            result.data["carrier_method"] = _safe_get(td5, 4)

        # REF - References (look for tracking numbers)
        refs = {}
        for ref_seg in _find_segments(segments, "REF"):
            qualifier = _safe_get(ref_seg, 1)
            value = _safe_get(ref_seg, 2)
            refs[qualifier] = value
            if qualifier == "CN":  # Carrier's Reference Number (tracking)
                result.data["tracking_number"] = value
            elif qualifier == "PO":
                result.data["po_number"] = value

        result.data["references"] = refs

        # SN1 - Shipped items
        shipped_items = []
        for sn1 in _find_segments(segments, "SN1"):
            item = {
                "line_number": _safe_get(sn1, 1),
                "quantity_shipped": _safe_get(sn1, 2),
                "unit": _safe_get(sn1, 3),
            }
            if len(sn1) > 4:
                item["quantity_ordered"] = _safe_get(sn1, 4)
            shipped_items.append(item)

        result.data["shipped_items"] = shipped_items

    except Exception as exc:
        result.errors.append(f"EDI 856 parse error: {exc}")
        logger.error(f"EDI 856 parse failed: {exc}")

    return result


# =============================================================================
# 810 - Invoice
# =============================================================================

def parse_edi_810(raw: str) -> EDIParseResult:
    """
    Parse an EDI 810 Invoice.

    Key segments:
      BIG - Beginning segment (invoice number, date, PO number)
      IT1 - Line items (quantity, price, product ID)
      TDS - Total monetary value
    """
    result = EDIParseResult(transaction_type="810")
    try:
        segments = _parse_segments(raw)
        result.segments = segments
        envelope = _parse_envelope(segments)
        result.control_number = envelope.get("control_number")
        result.sender_id = envelope.get("sender_id")
        result.receiver_id = envelope.get("receiver_id")

        # BIG segment
        big = _find_segment(segments, "BIG")
        if big:
            result.data["invoice_date"] = _safe_get(big, 1)
            result.data["invoice_number"] = _safe_get(big, 2)
            result.data["po_date"] = _safe_get(big, 3)
            result.data["po_number"] = _safe_get(big, 4)

        # IT1 - Line items
        invoice_lines = []
        for it1 in _find_segments(segments, "IT1"):
            line = {
                "line_number": _safe_get(it1, 1),
                "quantity_invoiced": _safe_get(it1, 2),
                "unit": _safe_get(it1, 3),
                "unit_price": _safe_get(it1, 4),
                "product_id_qualifier": _safe_get(it1, 6),
                "product_id": _safe_get(it1, 7),
            }
            invoice_lines.append(line)

        result.data["lines"] = invoice_lines

        # TDS - Total
        tds = _find_segment(segments, "TDS")
        if tds:
            result.data["total_minor"] = _safe_get(tds, 1)

    except Exception as exc:
        result.errors.append(f"EDI 810 parse error: {exc}")
        logger.error(f"EDI 810 parse failed: {exc}")

    return result


# =============================================================================
# 997 - Functional Acknowledgment
# =============================================================================

def parse_edi_997(raw: str) -> EDIParseResult:
    """
    Parse an EDI 997 Functional Acknowledgment.

    Key segments:
      AK1 - Functional group acknowledged
      AK9 - Functional group response (accepted/rejected)
    """
    result = EDIParseResult(transaction_type="997")
    try:
        segments = _parse_segments(raw)
        result.segments = segments
        envelope = _parse_envelope(segments)
        result.control_number = envelope.get("control_number")
        result.sender_id = envelope.get("sender_id")
        result.receiver_id = envelope.get("receiver_id")

        ak1 = _find_segment(segments, "AK1")
        if ak1:
            result.data["functional_id"] = _safe_get(ak1, 1)
            result.data["group_control"] = _safe_get(ak1, 2)

        ak9 = _find_segment(segments, "AK9")
        if ak9:
            status = _safe_get(ak9, 1)
            result.data["ack_status"] = status  # A=accepted, E=accepted with errors, R=rejected
            result.data["accepted"] = status in ("A", "E")
            result.data["included_count"] = _safe_get(ak9, 2)
            result.data["received_count"] = _safe_get(ak9, 3)
            result.data["accepted_count"] = _safe_get(ak9, 4)

    except Exception as exc:
        result.errors.append(f"EDI 997 parse error: {exc}")
        logger.error(f"EDI 997 parse failed: {exc}")

    return result


# =============================================================================
# AUTO-DETECT AND PARSE
# =============================================================================

_TRANSACTION_PARSERS = {
    "855": parse_edi_855,
    "856": parse_edi_856,
    "810": parse_edi_810,
    "997": parse_edi_997,
}


def parse_edi(raw: str) -> EDIParseResult:
    """
    Auto-detect the EDI transaction type from the ST segment and parse.

    Falls back to returning raw segments if the type is not supported.
    """
    try:
        segments = _parse_segments(raw)
    except Exception as exc:
        return EDIParseResult(
            transaction_type="unknown",
            errors=[f"Segment parse error: {exc}"],
        )

    st = _find_segment(segments, "ST")
    if not st:
        return EDIParseResult(
            transaction_type="unknown",
            segments=segments,
            errors=["No ST segment found — cannot determine transaction type"],
        )

    txn_type = _safe_get(st, 1)
    parser = _TRANSACTION_PARSERS.get(txn_type)
    if parser:
        return parser(raw)

    return EDIParseResult(
        transaction_type=txn_type,
        segments=segments,
        data={"message": f"EDI {txn_type} parsed but no specific handler — raw segments available"},
    )
