"""
Oracle Fusion Cloud ERP connector.

Auth: HTTP basic (integration user) — OAuth2 via IDCS possible later.
API:  REST — GET /fscmRestApi/resources/{version}/itemsV2
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

from provisioning_service.core.connectors.base import BaseConnector, ConnectorError

RESOURCE_VERSION = "11.13.18.05"
PAGE_SIZE = 100
TIMEOUT = 60


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
