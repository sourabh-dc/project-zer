"""
Base connector interface + canonical item schema.

Every ERP provider implements BaseConnector. The sync engine only ever
sees CanonicalItem objects — provider quirks stay inside the connector.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel


class CanonicalItem(BaseModel):
    """Provider-agnostic product record consumed by the sync engine."""
    external_id: str
    sku: str
    name: str
    description: Optional[str] = None
    category_name: Optional[str] = None     # find-or-created by the engine
    vendor_name: Optional[str] = None       # find-or-created by the engine
    purchase_price_minor: Optional[int] = None
    currency: str = "GBP"
    unit: Optional[str] = None
    ean: Optional[str] = None
    is_active: bool = True
    raw: Dict[str, Any] = {}


class CanonicalSupplier(BaseModel):
    """Provider-agnostic supplier record."""
    external_id: str
    name: str
    normalized_name: Optional[str] = None    # set by the resolution layer
    email: Optional[str] = None
    phone: Optional[str] = None
    currency: Optional[str] = None
    subsidiary: Optional[str] = None
    is_active: bool = True
    raw: Dict[str, Any] = {}


class CanonicalOrgDimension(BaseModel):
    """Provider-agnostic org unit (department / cost centre dimension)."""
    external_id: str
    name: str
    dimension_type: str = "department"       # department | cost_centre | location
    code: Optional[str] = None
    parent_external_id: Optional[str] = None
    is_active: bool = True
    raw: Dict[str, Any] = {}


class CanonicalSupplierProduct(BaseModel):
    """Supplier ↔ product relationship."""
    supplier_external_id: str
    product_external_id: str
    supplier_sku: Optional[str] = None
    purchase_price_minor: Optional[int] = None
    currency: Optional[str] = None
    raw: Dict[str, Any] = {}


class ConnectorError(Exception):
    """Raised for auth/transport failures. Carries a client-safe message."""


def fields_from_sample(sample: Dict[str, Any], custom_prefixes: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
    """Infer a schema field list from one raw provider record.

    Fallback for providers where live metadata introspection fails.
    """
    fields: List[Dict[str, Any]] = []
    for key, value in sample.items():
        if isinstance(value, bool):
            ftype = "boolean"
        elif isinstance(value, (int, float)):
            ftype = "number"
        elif isinstance(value, (dict, list)):
            ftype = "object"
        else:
            ftype = "string"
        fields.append({
            "name": key,
            "type": ftype,
            "label": key,
            "custom": any(key.startswith(p) for p in custom_prefixes),
        })
    return fields


# Canonical targets the mapping UI offers (canonical_field → label).
CANONICAL_FIELDS: List[Dict[str, str]] = [
    {"field": "external_id", "label": "External ID", "required": "true"},
    {"field": "sku", "label": "SKU / Item Code", "required": "true"},
    {"field": "name", "label": "Product Name", "required": "true"},
    {"field": "description", "label": "Description", "required": "false"},
    {"field": "category_name", "label": "Category", "required": "false"},
    {"field": "vendor_name", "label": "Vendor", "required": "false"},
    {"field": "purchase_price", "label": "Purchase Price", "required": "false"},
    {"field": "currency", "label": "Currency", "required": "false"},
    {"field": "unit", "label": "Unit of Measure", "required": "false"},
    {"field": "ean", "label": "Barcode / EAN", "required": "false"},
    {"field": "is_active", "label": "Active Flag (prefix source with ! to invert)", "required": "false"},
]


class BaseConnector(ABC):
    """Contract every ERP provider connector fulfils (deck slide 15).

    Lifecycle: configure, test, capabilities, schema, health, revoke.
    Reads: suppliers, products, locations, org dimensions, supplier–product,
           changesSince.
    Write: createPurchaseOrder only (slice 5).
    """

    provider_code: str = ""
    adapter_version: str = "0.1.0"

    def __init__(self, config: Dict[str, Any], credentials: Dict[str, Any]):
        self.config = config or {}
        self.credentials = credentials or {}

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """Verify credentials/connectivity. Returns (ok, message)."""

    @abstractmethod
    def fetch_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Fetch one page of raw provider items.

        Returns (raw_items, next_cursor). next_cursor=None means done.
        """

    def discover_schema(self) -> List[Dict[str, Any]]:
        """Discover the source system's item fields.

        Returns a flat list: [{"name", "type", "label", "custom"}].
        Used by the schema matcher: stored on the connection, drives the
        mapping UI dropdown and sync-time mapping validation.

        Default: empty list (provider does not support discovery).
        Implementations must be best-effort — fall back to a curated
        field list when live introspection fails.
        """
        return []

    def list_tables(self) -> Tuple[List[Dict[str, Any]], str]:
        """List queryable tables/record types in the source system.

        Returns (tables, source) where source is "live" or "fallback".
        Used by the connection setup UI to offer a table picker.
        Default: empty list (provider does not support a catalogue).
        """
        return ([], "unsupported")

    def preview_table(self, table: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Return up to ``limit`` sample rows from a source table.

        Implementations MUST validate the table identifier — it is
        typically interpolated into a query string.
        """
        raise ConnectorError(f"{self.provider_code or 'This provider'} does not support table preview")

    # ------------------------------------------------------------------
    # Contract: capabilities / health / revoke
    # ------------------------------------------------------------------

    def discover_capabilities(self) -> Dict[str, Any]:
        """Machine-readable capability declaration for this adapter.

        Drives write gate 1 (Declared) and the setup UI. Default: read
        products only, no writes.
        """
        return {
            "provider_code": self.provider_code,
            "adapter_version": self.adapter_version,
            "reads": {
                "products": True,
                "suppliers": False,
                "org_dimensions": False,
                "locations": False,
                "supplier_product": False,
                "changes_since": False,
            },
            "writes": {"create_purchase_order": False},
            "preview": False,
            "table_catalog": False,
        }

    def get_health(self) -> Dict[str, Any]:
        """Live adapter health: connectivity + latency. Sync-run stats are
        added by the route layer (they need the DB)."""
        started = time.monotonic()
        ok, message = self.test_connection()
        return {
            "ok": ok,
            "message": message,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "adapter_version": self.adapter_version,
        }

    def revoke_connection(self) -> Tuple[bool, str]:
        """Best-effort credential revocation at the provider. Default: nothing
        to revoke (tokens expire on their own)."""
        return True, "Nothing to revoke provider-side"

    # ------------------------------------------------------------------
    # Contract: additional reads (default = not supported)
    # ------------------------------------------------------------------

    def read_suppliers(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        raise ConnectorError(f"{self.provider_code} does not support readSuppliers")

    def read_org_dimensions(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        raise ConnectorError(f"{self.provider_code} does not support readOrganisationDimensions")

    def read_locations(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        raise ConnectorError(f"{self.provider_code} does not support readLocations")

    def read_supplier_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        raise ConnectorError(f"{self.provider_code} does not support readSupplierProductRelationships")

    def read_changes_since(
        self, object_type: str, since_iso: str, cursor: Optional[str]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Incremental read: records of ``object_type`` changed after ``since_iso``."""
        raise ConnectorError(f"{self.provider_code} does not support readChangesSince")

    # ------------------------------------------------------------------
    # Contract: governed write (slice 5 — default = not declared)
    # ------------------------------------------------------------------

    def create_purchase_order(self, po: Dict[str, Any], idempotency_key: str) -> Dict[str, Any]:
        """Create a PO in the ERP. MUST honour idempotency_key — a retry with
        the same key must not create a second PO."""
        raise ConnectorError(f"{self.provider_code} does not declare createPurchaseOrder")

    def normalize(self, raw: Dict[str, Any], field_map: Dict[str, str]) -> CanonicalItem:
        """Default normalizer: apply field_map (canonical_field <- provider_field).

        A provider field prefixed with "!" means boolean-invert the value
        (e.g. BC ``blocked`` / NetSuite ``isinactive`` → ``is_active``).
        """
        def pick(provider_field: Optional[str]) -> Any:
            if not provider_field:
                return None
            if provider_field.startswith("!"):
                val = raw.get(provider_field[1:])
                if val is None:
                    return None
                if isinstance(val, str):
                    return val.strip().lower() not in ("true", "t", "yes", "y", "1")
                return not bool(val)
            return raw.get(provider_field)

        def pick_money(provider_field: Optional[str]) -> Optional[int]:
            val = pick(provider_field)
            if val is None:
                return None
            try:
                return int(round(float(val) * 100))
            except (TypeError, ValueError):
                return None

        return CanonicalItem(
            external_id=str(pick(field_map.get("external_id")) or ""),
            sku=str(pick(field_map.get("sku")) or "").strip(),
            name=str(pick(field_map.get("name")) or "").strip(),
            description=pick(field_map.get("description")),
            category_name=pick(field_map.get("category_name")),
            vendor_name=pick(field_map.get("vendor_name")),
            purchase_price_minor=pick_money(field_map.get("purchase_price")),
            currency=str(pick(field_map.get("currency")) or "GBP"),
            unit=pick(field_map.get("unit")),
            ean=pick(field_map.get("ean")),
            is_active=bool(pick(field_map.get("is_active")) if pick(field_map.get("is_active")) is not None else True),
            raw=raw,
        )
