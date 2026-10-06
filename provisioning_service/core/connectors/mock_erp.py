"""
MockERP connector — in-memory fake ERP for the behavioural test suite.

Proves the adapter contract without a live vendor account (deck slice 1).
Supports every contract read, changesSince via per-record timestamps,
and an idempotent createPurchaseOrder. Failure injection via config:

    config = {
        "fail_auth": bool,          # test_connection fails
        "fail_on_page": int,        # raise ConnectorError on page N (1-based)
        "products": [...], "suppliers": [...], ...
    }
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from provisioning_service.core.connectors.base import BaseConnector, ConnectorError

PAGE_SIZE = 3  # small on purpose — forces multi-page behaviour in tests

_DEFAULT_PRODUCTS = [
    {"sku": "GLV-NIT-L", "name": "NIT GLOVE BLU PF LG", "price": 8.5, "vendor": "METSA",
     "updated_at": "2026-01-01T00:00:00"},
    {"sku": "PPR-A4-80", "name": "COPY PAPER A4 80GSM", "price": 4.2, "vendor": "METSA",
     "updated_at": "2026-01-02T00:00:00"},
    {"sku": "PEN-BLK", "name": "BALLPOINT PEN BLACK", "price": 0.35, "vendor": "BIC",
     "updated_at": "2026-01-03T00:00:00"},
    {"sku": "CLN-SPRY", "name": "CLEANING SPRAY 750ML", "price": 2.1, "vendor": "DIVERSEY",
     "updated_at": "2026-01-04T00:00:00"},
    {"sku": "TWL-HND", "name": "HAND TOWEL 2PLY", "price": 12.0, "vendor": "METSA",
     "updated_at": "2026-01-05T00:00:00"},
]

_DEFAULT_SUPPLIERS = [
    {"id": "V1", "name": "METSÄ TISSUE LTD", "email": "sales@metsa.example",
     "updated_at": "2026-01-01T00:00:00"},
    {"id": "V2", "name": "BIC UK", "email": "orders@bic.example",
     "updated_at": "2026-01-02T00:00:00"},
]


class MockERPConnector(BaseConnector):
    provider_code = "mockerp"
    adapter_version = "1.0.0"

    # ── lifecycle ────────────────────────────────────────────────

    def test_connection(self) -> Tuple[bool, str]:
        if self.config.get("fail_auth"):
            return False, "MockERP: authentication failed (fail_auth set)"
        return True, "MockERP connection OK"

    def discover_capabilities(self) -> Dict[str, Any]:
        caps = super().discover_capabilities()
        caps["reads"].update({
            "suppliers": True, "org_dimensions": True, "locations": True,
            "supplier_product": True, "changes_since": True,
        })
        caps["writes"]["create_purchase_order"] = True
        caps["preview"] = True
        caps["table_catalog"] = True
        return caps

    # ── reads ────────────────────────────────────────────────────

    def _page(self, rows: List[Dict[str, Any]], cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        offset = int(cursor) if cursor else 0
        page_no = offset // PAGE_SIZE + 1
        fail_on = self.config.get("fail_on_page")
        if fail_on and page_no == int(fail_on):
            raise ConnectorError(f"MockERP: injected failure on page {page_no}")
        chunk = rows[offset:offset + PAGE_SIZE]
        next_cursor = str(offset + PAGE_SIZE) if offset + PAGE_SIZE < len(rows) else None
        return [dict(r) for r in chunk], next_cursor

    def fetch_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        return self._page(self.config.get("products", _DEFAULT_PRODUCTS), cursor)

    def read_suppliers(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        return self._page(self.config.get("suppliers", _DEFAULT_SUPPLIERS), cursor)

    def read_org_dimensions(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        return self._page(self.config.get("org_dimensions", [
            {"id": "D1", "name": "Finance", "updated_at": "2026-01-01T00:00:00"},
        ]), cursor)

    def read_locations(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        return self._page(self.config.get("locations", [
            {"id": "L1", "name": "London HQ", "updated_at": "2026-01-01T00:00:00"},
        ]), cursor)

    def read_supplier_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        return self._page(self.config.get("supplier_products", [
            {"supplier": "V1", "sku": "GLV-NIT-L", "vendorcode": "MT-1001"},
        ]), cursor)

    def read_changes_since(
        self, object_type: str, since_iso: str, cursor: Optional[str]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        source = {
            "product": self.config.get("products", _DEFAULT_PRODUCTS),
            "supplier": self.config.get("suppliers", _DEFAULT_SUPPLIERS),
        }.get(object_type)
        if source is None:
            raise ConnectorError(f"MockERP: unsupported object_type {object_type!r}")
        changed = [r for r in source if r.get("updated_at", "") > since_iso]
        return self._page(changed, cursor)

    # ── catalogue / preview ──────────────────────────────────────

    def list_tables(self) -> Tuple[List[Dict[str, Any]], str]:
        return ([{"name": t} for t in ("item", "vendor", "department", "location")], "live")

    def preview_table(self, table: str, limit: int = 15) -> List[Dict[str, Any]]:
        data = {
            "item": self.config.get("products", _DEFAULT_PRODUCTS),
            "vendor": self.config.get("suppliers", _DEFAULT_SUPPLIERS),
        }.get(table)
        if data is None:
            raise ConnectorError(f"Invalid table name: {table!r}")
        return [dict(r) for r in data[:limit]]

    # ── governed write ───────────────────────────────────────────

    def create_purchase_order(self, po: Dict[str, Any], idempotency_key: str) -> Dict[str, Any]:
        """Idempotent: same key → same record, no duplicate."""
        if not idempotency_key:
            raise ConnectorError("MockERP: idempotency_key required")
        store = self.config.setdefault("_po_store", {})
        if idempotency_key in store:
            return {"ok": True, "external_id": idempotency_key, "duplicated": False,
                    "mock_id": store[idempotency_key]["mock_id"], "idempotent_replay": True}
        mock_id = f"MOCK-PO-{len(store) + 1:04d}"
        store[idempotency_key] = {"mock_id": mock_id, "po": po,
                                  "created_at": datetime.now(timezone.utc).isoformat()}
        return {"ok": True, "external_id": idempotency_key, "duplicated": False,
                "mock_id": mock_id, "idempotent_replay": False}
