"""
Oracle NetSuite connector.

Auth: Token-Based Auth (TBA) — HMAC-SHA256 signed requests.
API:  SuiteQL — POST /services/rest/query/v1/suiteql
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid as _uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from provisioning_service.core.connectors.base import BaseConnector, ConnectorError, fields_from_sample

PAGE_SIZE = 500
TIMEOUT = 60

ITEMS_QUERY = """
SELECT itemid, displayname, salesdescription, purchasedescription,
       baseprice, currency, itemtype, isinactive, upccode, class
FROM item
WHERE isinactive = 'F'
ORDER BY itemid
"""

# Curated fallback — the standard item fields this connector queries.
DEFAULT_ITEM_FIELDS = [
    {"name": "itemid", "type": "string", "label": "Item ID / SKU", "custom": False},
    {"name": "displayname", "type": "string", "label": "Display Name", "custom": False},
    {"name": "salesdescription", "type": "string", "label": "Sales Description", "custom": False},
    {"name": "purchasedescription", "type": "string", "label": "Purchase Description", "custom": False},
    {"name": "baseprice", "type": "number", "label": "Base Price", "custom": False},
    {"name": "currency", "type": "string", "label": "Currency", "custom": False},
    {"name": "itemtype", "type": "string", "label": "Item Type", "custom": False},
    {"name": "isinactive", "type": "boolean", "label": "Inactive (invert with !)", "custom": False},
    {"name": "upccode", "type": "string", "label": "UPC / Barcode", "custom": False},
    {"name": "class", "type": "string", "label": "Class / Category", "custom": False},
]


class NetSuiteConnector(BaseConnector):
    provider_code = "netsuite"

    def _account(self) -> str:
        account = (self.config.get("account_id") or "").strip()
        if not account:
            raise ConnectorError("Missing config: account_id")
        return account

    def _base_url(self) -> str:
        # SuiteTalk REST domain uses hyphenated account id
        return f"https://{self._account().replace('_', '-').lower()}.suitetalk.api.netsuite.com"

    def _auth_header(self, method: str, url: str) -> str:
        creds = self.credentials
        required = ["consumer_key", "consumer_secret", "token_id", "token_secret"]
        missing = [k for k in required if not creds.get(k)]
        if missing:
            raise ConnectorError(f"Missing credentials: {', '.join(missing)}")

        nonce = _uuid.uuid4().hex
        timestamp = str(int(time.time()))
        realm = self._account()

        params = {
            "oauth_consumer_key": creds["consumer_key"],
            "oauth_nonce": nonce,
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": timestamp,
            "oauth_token": creds["token_id"],
            "oauth_version": "1.0",
        }
        param_str = "&".join(f"{quote(k)}={quote(v)}" for k, v in sorted(params.items()))
        base_string = "&".join([method.upper(), quote(url, safe=""), quote(param_str, safe="")])
        signing_key = f"{quote(creds['consumer_secret'], safe='')}&{quote(creds['token_secret'], safe='')}"
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha256).digest()
        ).decode()

        params["oauth_signature"] = signature
        header = ", ".join(f'{k}="{quote(v, safe="")}"' for k, v in params.items())
        return f'OAuth realm="{realm}", {header}'

    def _query(self, query: str, offset: int = 0) -> Dict[str, Any]:
        url = f"{self._base_url()}/services/rest/query/v1/suiteql"
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": self._auth_header("POST", url),
                    "Content-Type": "application/json",
                    "Prefer": "transient",
                },
                json={"q": f"{query} LIMIT {PAGE_SIZE} OFFSET {offset}"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except ConnectorError:
            raise
        except requests.RequestException as e:
            raise ConnectorError(f"NetSuite SuiteQL failed: {e}")
        except ValueError as e:
            raise ConnectorError(f"NetSuite response malformed: {e}")

    def test_connection(self) -> Tuple[bool, str]:
        try:
            body = self._query("SELECT itemid FROM item", offset=0)
            if "items" in body:
                return True, "Connection OK"
            return False, "Unexpected SuiteQL response"
        except ConnectorError as e:
            return False, str(e)

    def fetch_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """cursor = numeric offset as string."""
        offset = int(cursor) if cursor else 0
        body = self._query(ITEMS_QUERY, offset=offset)
        items = body.get("items", [])
        has_more = bool(body.get("hasMore"))
        next_cursor = str(offset + PAGE_SIZE) if has_more else None
        return items, next_cursor

    def discover_schema(self) -> List[Dict[str, Any]]:
        """Discover item fields via the REST metadata catalog.

        Custom fields (``custitem_*``) are flagged custom=True. The
        catalog is not enabled on every account — falls back to the
        curated standard field list.
        """
        url = f"{self._base_url()}/services/rest/record/v1/metadata-catalog/item"
        try:
            resp = requests.get(
                url,
                headers={"Authorization": self._auth_header("GET", url)},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            fields: List[Dict[str, Any]] = []
            # Catalog shape: {"fields": {"<name": {...}}} or nested links — parse defensively
            raw_fields = data.get("fields") or {}
            if isinstance(raw_fields, dict):
                for name, meta in raw_fields.items():
                    fields.append({
                        "name": name,
                        "type": str((meta or {}).get("type", "string")).lower(),
                        "label": (meta or {}).get("label", name),
                        "custom": name.startswith("custitem_"),
                    })
            if fields:
                return fields
        except Exception as e:
            from provisioning_service.utils.logger import logger
            logger.warning(f"NetSuite metadata catalog failed, using defaults: {e}")
        return list(DEFAULT_ITEM_FIELDS)
