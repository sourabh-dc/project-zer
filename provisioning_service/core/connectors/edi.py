"""
EDI / cXML dispatch (deck slice 6 — skeleton).

Separate from the ERP write path on purpose: the ERP write is governed by
the four gates and acknowledged synchronously; supplier dispatch is a
downstream, independently-retried step. A failed EDI transmission must
never roll back an acknowledged ERP PO.

Supported profiles:
  - "mock"   : records the dispatch, always succeeds (contract tests)
  - "cxml"   : POST a cXML OrderRequest to the supplier endpoint
  - "edi850" : X12 850 over AS2/SFTP — transport plug point (not built)

Retry policy lives with the caller (po_write_routes): transient transport
errors are retried with backoff; the dispatch row is the audit trail.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from provisioning_service.utils.logger import logger

DEFAULT_TIMEOUT = 30


class DispatchError(Exception):
    """Raised on transport failure. Carries retry_class: transient|permanent."""
    def __init__(self, message: str, retry_class: str = "transient"):
        super().__init__(message)
        self.retry_class = retry_class


def build_cxml_order_request(po: Dict[str, Any], *, sender_identity: str, shared_secret: str) -> str:
    """Minimal cXML OrderRequest document from a canonical PO dict."""
    payload_id = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc).isoformat()
    order_id = po.get("order_id", "")
    lines = []
    for i, line in enumerate(po.get("lines", []), start=1):
        lines.append(
            f'<ItemOut lineNumber="{i}" quantity="{line.get("quantity", 1)}">'
            f'<ItemID><SupplierPartID>{line.get("supplier_sku", "")}</SupplierPartID></ItemID>'
            f'<ItemDetail><UnitPrice><Money currency="{po.get("currency", "GBP")}">'
            f'{(line.get("unit_price_minor", 0) or 0) / 100:.2f}</Money></UnitPrice>'
            f'<Description xml:lang="en">{line.get("description", "")}</Description>'
            f'<UnitOfMeasure>{line.get("unit", "EA")}</UnitOfMeasure></ItemDetail></ItemOut>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<cXML payloadID="{payload_id}" timestamp="{timestamp}">'
        f'<Header><From><Credential domain="NetworkID"><Identity>{sender_identity}</Identity></Credential></From>'
        f'<To><Credential domain="NetworkID"><Identity>{po.get("supplier_id", "")}</Identity></Credential></To>'
        f'<Sender><Credential domain="NetworkID"><Identity>{sender_identity}</Identity>'
        f'<SharedSecret>{shared_secret}</SharedSecret></Credential>'
        '<UserAgent>ZeroQue</UserAgent></Sender></Header>'
        f'<Request><OrderRequest><OrderRequestHeader orderID="{order_id}" orderDate="{timestamp}" type="new">'
        f'<Total><Money currency="{po.get("currency", "GBP")}">{(po.get("total_minor", 0) or 0) / 100:.2f}</Money></Total>'
        '</OrderRequestHeader>'
        + "".join(lines) +
        '</OrderRequest></Request></cXML>'
    )


def dispatch_to_supplier(
    po: Dict[str, Any],
    *,
    profile: str,
    endpoint: Optional[str] = None,
    credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send an approved PO to the supplier. Returns a dispatch receipt.

    Raises DispatchError on transport failure — the caller records it and
    schedules retry; nothing here touches the ERP write state.
    """
    credentials = credentials or {}

    if profile == "mock":
        return {
            "profile": "mock",
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "supplier_ref": f"MOCK-{uuid.uuid4().hex[:8].upper()}",
            "status": "accepted",
        }

    if profile == "cxml":
        if not endpoint:
            raise DispatchError("cXML profile requires an endpoint", retry_class="permanent")
        document = build_cxml_order_request(
            po,
            sender_identity=credentials.get("sender_identity", "zeroque"),
            shared_secret=credentials.get("shared_secret", ""),
        )
        try:
            resp = requests.post(
                endpoint,
                data=document.encode("utf-8"),
                headers={"Content-Type": "text/xml"},
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise DispatchError(f"cXML transport failed: {e}", retry_class="transient") from e
        if resp.status_code >= 500:
            raise DispatchError(f"Supplier endpoint {resp.status_code}", retry_class="transient")
        if resp.status_code >= 400:
            raise DispatchError(f"Supplier rejected dispatch: {resp.status_code}", retry_class="permanent")
        return {
            "profile": "cxml",
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "http_status": resp.status_code,
            "response_body": resp.text[:2000],
            "status": "sent",
        }

    if profile == "edi850":
        # X12 850 over AS2/SFTP — transport plug point, not built yet.
        raise DispatchError("EDI 850 transport not implemented", retry_class="permanent")

    raise DispatchError(f"Unknown dispatch profile '{profile}'", retry_class="permanent")
