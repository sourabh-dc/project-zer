"""
Oracle Fusion Cloud ERP connector.

Auth: HTTP basic (integration user) — OAuth2 via IDCS possible later.
API:  REST — GET /fscmRestApi/resources/{version}/itemsV2
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

from provisioning_service.core.connectors.base import BaseConnector, ConnectorError, fields_from_sample

RESOURCE_VERSION = "11.13.18.05"
PAGE_SIZE = 100
TIMEOUT = 60

# Curated fallback — the standard itemsV2 fields this connector queries.
DEFAULT_ITEM_FIELDS = [
    {"name": "ItemNumber", "type": "string", "label": "Item Number / SKU", "custom": False},
    {"name": "ItemDescription", "type": "string", "label": "Description", "custom": False},
    {"name": "LongDescription", "type": "string", "label": "Long Description", "custom": False},
    {"name": "ListPrice", "type": "number", "label": "List Price", "custom": False},
    {"name": "CurrencyCode", "type": "string", "label": "Currency", "custom": False},
    {"name": "ItemClass", "type": "string", "label": "Item Class / Category", "custom": False},
    {"name": "OrganizationCode", "type": "string", "label": "Organization", "custom": False},
    {"name": "ItemStatusValue", "type": "string", "label": "Status", "custom": False},
]


class OracleERPConnector(BaseConnector):
    provider_code = "oracle_erp"

    def _base(self) -> str:
        base = (self.config.get("base_url") or "").rstrip("/")
        if not base:
            raise ConnectorError("Missing config: base_url")
        return base

    def _auth(self) -> Tuple[str, str]:
        user = self.credentials.get("username", "")
        password = self.credentials.get("password", "")
        if not user or not password:
            raise ConnectorError("Missing credentials: username/password")
        return user, password

    def _items_url(self) -> str:
        return f"{self._base()}/fscmRestApi/resources/{RESOURCE_VERSION}/itemsV2"

    def _params(self, offset: int) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "limit": PAGE_SIZE,
            "offset": offset,
            "fields": "ItemNumber,ItemDescription,LongDescription,ListPrice,CurrencyCode,"
                      "ItemClass,OrganizationCode,ItemStatusValue",
            "onlyData": "true",
        }
        org = self.config.get("organization_code")
        if org:
            params["q"] = f"OrganizationCode='{org}'"
        return params

    def test_connection(self) -> Tuple[bool, str]:
        try:
            resp = requests.get(
                self._items_url(),
                auth=self._auth(),
                params={**self._params(0), "limit": 1},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                return True, "Connection OK"
            return False, f"Oracle ERP returned HTTP {resp.status_code}: {resp.text[:200]}"
        except ConnectorError as e:
            return False, str(e)
        except requests.RequestException as e:
            return False, f"Network error: {e}"

    def fetch_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """cursor = numeric offset as string."""
        offset = int(cursor) if cursor else 0
        try:
            resp = requests.get(
                self._items_url(),
                auth=self._auth(),
                params=self._params(offset),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except ConnectorError:
            raise
        except requests.RequestException as e:
            raise ConnectorError(f"Oracle ERP items fetch failed: {e}")

        body = resp.json()
        items = body.get("items", [])
        has_more = bool(body.get("hasMore"))
        next_cursor = str(offset + PAGE_SIZE) if has_more else None
        return items, next_cursor

    def discover_schema(self) -> List[Dict[str, Any]]:
        """Discover itemsV2 fields via the Oracle REST ``describe`` action.

        Flexfield (custom) attributes arrive under ``*_EFF`` / ``*_DFF``
        naming and are flagged custom=True. Falls back to the curated
        standard field list when describe is unavailable.
        """
        try:
            resp = requests.get(
                f"{self._items_url()}/describe",
                auth=self._auth(),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            fields: List[Dict[str, Any]] = []
            resources = data.get("Resources") or {}
            item_res = resources.get("itemsV2") or {}
            for attr in item_res.get("attributes") or []:
                name = attr.get("name", "")
                if not name:
                    continue
                fields.append({
                    "name": name,
                    "type": str(attr.get("type", "string")).lower(),
                    "label": attr.get("title", name),
                    "custom": name.endswith(("_EFF", "_DFF")) or "Flexfield" in name,
                })
            if fields:
                return fields
        except Exception as e:
            from provisioning_service.utils.logger import logger
            logger.warning(f"Oracle describe failed, using defaults: {e}")
        return list(DEFAULT_ITEM_FIELDS)
