"""
SAP Business One connector (Service Layer).

Auth: session login — POST /b1s/v1/Login → SessionId cookie.
API:  OData-ish — GET /b1s/v1/Items with $top/$skip.
Note: prices live in ItemPrices; the connection config picks one price list.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

from provisioning_service.core.connectors.base import BaseConnector, ConnectorError, fields_from_sample

PAGE_SIZE = 100
TIMEOUT = 30


class SapB1Connector(BaseConnector):
    provider_code = "sap_b1"

    def __init__(self, config, credentials):
        super().__init__(config, credentials)
        self._session_cookie: Optional[str] = None
        self._price_list: Optional[int] = None
        pl = self.config.get("price_list")
        if pl is not None:
            try:
                self._price_list = int(pl)
            except (TypeError, ValueError):
                raise ConnectorError("config.price_list must be an integer")

    def _base(self) -> str:
        base = (self.config.get("base_url") or "").rstrip("/")
        if not base:
            raise ConnectorError("Missing config: base_url")
        return base

    def _login(self) -> str:
        if self._session_cookie:
            return self._session_cookie
        try:
            resp = requests.post(
                f"{self._base()}/b1s/v1/Login",
                json={
                    "CompanyDB": self.config.get("company_db", ""),
                    "UserName": self.credentials.get("username", ""),
                    "Password": self.credentials.get("password", ""),
                },
                timeout=TIMEOUT,
                verify=not self.config.get("allow_insecure_ssl", False),
            )
            resp.raise_for_status()
            self._session_cookie = resp.cookies.get("B1SESSION")
            if not self._session_cookie:
                raise ConnectorError("SAP B1 login succeeded but no B1SESSION cookie returned")
            return self._session_cookie
        except requests.RequestException as e:
            raise ConnectorError(f"SAP B1 login failed: {e}")

    def _headers(self) -> Dict[str, str]:
        return {"Cookie": f"B1SESSION={self._login()}", "Accept": "application/json"}

    def test_connection(self) -> Tuple[bool, str]:
        try:
            resp = requests.get(
                f"{self._base()}/b1s/v1/Items",
                headers=self._headers(),
                params={"$top": 1, "$select": "ItemCode"},
                timeout=TIMEOUT,
                verify=not self.config.get("allow_insecure_ssl", False),
            )
            if resp.status_code == 200:
                return True, "Connection OK"
            return False, f"SAP B1 returned HTTP {resp.status_code}: {resp.text[:200]}"
        except ConnectorError as e:
            return False, str(e)
        except requests.RequestException as e:
            return False, f"Network error: {e}"

    def fetch_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """cursor = numeric skip offset as string."""
        skip = int(cursor) if cursor else 0
        try:
            resp = requests.get(
                f"{self._base()}/b1s/v1/Items",
                headers=self._headers(),
                params={
                    "$top": PAGE_SIZE,
                    "$skip": skip,
                    "$filter": "SalesItem eq true and Valid eq 'Y'",
                },
                timeout=TIMEOUT,
                verify=not self.config.get("allow_insecure_ssl", False),
            )
            resp.raise_for_status()
        except ConnectorError:
            raise
        except requests.RequestException as e:
            raise ConnectorError(f"SAP B1 items fetch failed: {e}")

        items = resp.json().get("value", [])

        # Flatten the chosen price list onto the item for the default map.
        if self._price_list is not None:
            for item in items:
                for price in item.get("ItemPrices", []) or []:
                    if price.get("PriceList") == self._price_list:
                        item["_price"] = price.get("Price")
                        break

        next_cursor = str(skip + PAGE_SIZE) if len(items) == PAGE_SIZE else None
        return items, next_cursor

    def discover_schema(self) -> List[Dict[str, Any]]:
        """Discover Item fields from the Service Layer $metadata.

        SAP B1 user-defined fields appear as ``U_*`` properties and are
        flagged custom=True. Falls back to sample-record inference.
        """
        try:
            resp = requests.get(
                f"{self._base()}/b1s/v1/$metadata",
                headers=self._headers(),
                timeout=TIMEOUT,
                verify=not self.config.get("allow_insecure_ssl", False),
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            fields: List[Dict[str, Any]] = []
            for entity_type in root.iter("{http://docs.oasis-open.org/odata/ns/edm}EntityType"):
                if entity_type.get("Name") != "Item":
                    continue
                for prop in entity_type.iter("{http://docs.oasis-open.org/odata/ns/edm}Property"):
                    name = prop.get("Name", "")
                    edm_type = (prop.get("Type") or "").replace("Edm.", "").lower()
                    fields.append({
                        "name": name,
                        "type": edm_type or "string",
                        "label": name,
                        "custom": name.startswith("U_"),
                    })
                break
            if fields:
                return fields
        except Exception as e:
            from provisioning_service.utils.logger import logger
            logger.warning(f"SAP B1 $metadata discovery failed, sampling instead: {e}")

        try:
            sample, _ = self.fetch_products(None)
            if sample:
                return fields_from_sample(sample[0], custom_prefixes=("U_",))
        except Exception:
            pass
        return []
