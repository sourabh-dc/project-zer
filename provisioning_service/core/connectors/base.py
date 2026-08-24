"""
Base connector interface + canonical item schema.

Every ERP provider implements BaseConnector. The sync engine only ever
sees CanonicalItem objects — provider quirks stay inside the connector.
"""
from __future__ import annotations

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
    """Contract every ERP provider connector fulfils."""

    provider_code: str = ""

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
