"""
Microsoft Dynamics 365 Business Central connector.

Auth: OAuth2 client credentials (Entra ID).
API:  OData v4 — GET /api/v2.0/companies({companyId})/items
Docs: https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

from provisioning_service.core.connectors.base import BaseConnector, ConnectorError, fields_from_sample

TOKEN_URL = "https://login.microsoftonline.com/{aad_tenant}/oauth2/v2.0/token"
API_SCOPE = "https://api.businesscentral.dynamics.com/.default"
API_BASE = "https://api.businesscentral.dynamics.com/v2.0/{aad_tenant}/{environment}"

PAGE_SIZE = 100
TIMEOUT = 30


class DynamicsBCConnector(BaseConnector):
    provider_code = "dynamics_bc"

    def _token(self) -> str:
        aad_tenant = self.config.get("aad_tenant_id")
        if not aad_tenant:
            raise ConnectorError("Missing config: aad_tenant_id")
        try:
            resp = requests.post(
                TOKEN_URL.format(aad_tenant=aad_tenant),
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.credentials.get("client_id", ""),
                    "client_secret": self.credentials.get("client_secret", ""),
                    "scope": API_SCOPE,
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()["access_token"]
        except requests.RequestException as e:
            raise ConnectorError(f"BC token request failed: {e}")
        except (KeyError, ValueError) as e:
            raise ConnectorError(f"BC token response malformed: {e}")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}

    def _items_url(self) -> str:
        environment = self.config.get("environment", "production")
        company_id = self.config.get("company_id")
        aad_tenant = self.config.get("aad_tenant_id")
        if not company_id:
            raise ConnectorError("Missing config: company_id")
        base = API_BASE.format(aad_tenant=aad_tenant, environment=environment)
        return f"{base}/companies({company_id})/items"

    def test_connection(self) -> Tuple[bool, str]:
        try:
            resp = requests.get(
                self._items_url(),
                headers=self._headers(),
                params={"$top": 1},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                return True, "Connection OK"
            return False, f"BC returned HTTP {resp.status_code}: {resp.text[:200]}"
        except ConnectorError as e:
            return False, str(e)
        except requests.RequestException as e:
            return False, f"Network error: {e}"

    def fetch_products(self, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """cursor = full nextLink URL (or None for first page)."""
        url = cursor or self._items_url()
        params = None if cursor else {
            "$top": PAGE_SIZE,
            "$filter": "type eq 'Inventory' or type eq 'Non-Inventory'",
        }
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=TIMEOUT)
            resp.raise_for_status()
        except ConnectorError:
            raise
        except requests.RequestException as e:
            raise ConnectorError(f"BC items fetch failed: {e}")

        body = resp.json()
        items = body.get("value", [])
        next_link = body.get("@odata.nextLink")
        return items, next_link

    def discover_schema(self) -> List[Dict[str, Any]]:
        """Discover Item fields from the OData $metadata document.

        Falls back to inferring from one sample item when metadata
        parsing fails (extension fields still appear in samples).
        """
        environment = self.config.get("environment", "production")
        aad_tenant = self.config.get("aad_tenant_id")
        base = API_BASE.format(aad_tenant=aad_tenant, environment=environment)
        try:
            resp = requests.get(
                f"{base}/api/v2.0/$metadata",
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            fields: List[Dict[str, Any]] = []
            for entity_type in root.iter("{http://docs.oasis-open.org/odata/ns/edm}EntityType"):
                if entity_type.get("Name") != "Item":
                    continue
                for prop in entity_type.iter("{http://docs.oasis-open.org/odata/ns/edm}Property"):
                    edm_type = (prop.get("Type") or "").replace("Edm.", "").lower()
                    fields.append({
                        "name": prop.get("Name", ""),
                        "type": edm_type or "string",
                        "label": prop.get("Name", ""),
                        "custom": False,
                    })
                break
            if fields:
                return fields
        except Exception as e:
            logger_warning = f"BC $metadata discovery failed, sampling instead: {e}"
            from provisioning_service.utils.logger import logger
            logger.warning(logger_warning)

        # Fallback: infer from one live item
        try:
            sample, _ = self.fetch_products(None)
            if sample:
                return fields_from_sample(sample[0])
        except Exception:
            pass
        return []
