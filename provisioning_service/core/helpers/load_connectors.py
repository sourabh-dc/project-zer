"""
Seed the connector_providers catalogue (idempotent upsert).

Each provider defines:
  - config_schema: fields the setup form must collect (non-secret + secret)
  - default_field_map: provider field -> canonical field
    ("!" prefix = boolean invert, e.g. "!blocked" -> is_active)
"""
from __future__ import annotations

from typing import Any, Dict, List

from provisioning_service.Models import ConnectorProvider
from provisioning_service.core.db_config import SessionLocal

PROVIDERS: List[Dict[str, Any]] = [
    {
        "provider_code": "dynamics_bc",
        "display_name": "Microsoft Dynamics 365 Business Central",
        "auth_type": "oauth2",
        "config_schema": {
            "config": [
                {"key": "aad_tenant_id", "label": "Entra tenant ID", "required": True},
                {"key": "environment", "label": "Environment", "required": False, "default": "production"},
                {"key": "company_id", "label": "Company ID (GUID)", "required": True},
            ],
            "credentials": [
                {"key": "client_id", "label": "Client ID", "required": True},
                {"key": "client_secret", "label": "Client secret", "required": True, "secret": True},
            ],
        },
        "default_field_map": {
            "external_id": "id",
            "sku": "number",
            "name": "displayName",
            "description": "description",
            "category_name": "itemCategoryCode",
            "purchase_price": "unitCost",
            "unit": "baseUnitOfMeasureCode",
            "ean": "gtin",
            "is_active": "!blocked",
        },
    },
    {
        "provider_code": "sap_b1",
        "display_name": "SAP Business One",
        "auth_type": "basic",
        "config_schema": {
            "config": [
                {"key": "base_url", "label": "Service Layer URL", "required": True,
                 "placeholder": "https://sap-server:50000"},
                {"key": "company_db", "label": "Company database", "required": True},
                {"key": "price_list", "label": "Price list number", "required": True},
                {"key": "allow_insecure_ssl", "label": "Allow self-signed SSL (dev)", "required": False, "type": "bool"},
            ],
            "credentials": [
                {"key": "username", "label": "SAP username", "required": True},
                {"key": "password", "label": "SAP password", "required": True, "secret": True},
            ],
        },
        "default_field_map": {
            "external_id": "ItemCode",
            "sku": "ItemCode",
            "name": "ItemName",
            "description": "SalesUnit",
            "category_name": "ItemsGroupCode",
            "purchase_price": "_price",
            "unit": "SalesUnit",
            "ean": "CodeBars",
        },
    },
    {
        "provider_code": "netsuite",
        "display_name": "Oracle NetSuite",
        "auth_type": "oauth2_m2m",
        "config_schema": {
            "config": [
                {"key": "account_id", "label": "Account ID", "required": True,
                 "placeholder": "1234567_SB1"},
                {"key": "auth_method", "label": "Auth method", "required": False,
                 "type": "select", "options": ["oauth2_m2m", "tba"], "default": "oauth2_m2m"},
            ],
            "credentials": [
                # OAuth 2.0 Client Credentials (M2M) — recommended
                {"key": "client_id", "label": "Client ID (M2M)", "required": False},
                {"key": "certificate_id", "label": "Certificate ID (M2M)", "required": False},
                {"key": "private_key", "label": "Private key PEM (M2M)", "required": False,
                 "secret": True, "type": "textarea"},
                {"key": "algorithm", "label": "Signing algorithm (PS256/ES256)", "required": False,
                 "default": "PS256"},
                # TBA — legacy fallback
                {"key": "consumer_key", "label": "Consumer key (TBA)", "required": False, "secret": True},
                {"key": "consumer_secret", "label": "Consumer secret (TBA)", "required": False, "secret": True},
                {"key": "token_id", "label": "Token ID (TBA)", "required": False, "secret": True},
                {"key": "token_secret", "label": "Token secret (TBA)", "required": False, "secret": True},
            ],
        },
        "default_field_map": {
            "external_id": "itemid",
            "sku": "itemid",
            "name": "displayname",
            "description": "salesdescription",
            "category_name": "class",
            "purchase_price": "baseprice",
            "currency": "currency",
            "ean": "upccode",
        },
    },
    {
        "provider_code": "oracle_erp",
        "display_name": "Oracle Fusion Cloud ERP",
        "auth_type": "basic",
        "config_schema": {
            "config": [
                {"key": "base_url", "label": "Base URL", "required": True,
                 "placeholder": "https://your-pod.fa.em2.oraclecloud.com"},
                {"key": "organization_code", "label": "Organization code", "required": True},
            ],
            "credentials": [
                {"key": "username", "label": "Integration username", "required": True},
                {"key": "password", "label": "Password", "required": True, "secret": True},
            ],
        },
        "default_field_map": {
            "external_id": "ItemNumber",
            "sku": "ItemNumber",
            "name": "ItemDescription",
            "description": "LongDescription",
            "category_name": "ItemClass",
            "purchase_price": "ListPrice",
            "currency": "CurrencyCode",
        },
    },
]


def seed_connector_providers() -> int:
    """Upsert provider catalogue. Returns number of new providers added."""
    session = SessionLocal()
    added = 0
    try:
        existing = {p.provider_code: p for p in session.query(ConnectorProvider).all()}
        for p in PROVIDERS:
            row = existing.get(p["provider_code"])
            if row is None:
                session.add(ConnectorProvider(**p, is_active=True))
                added += 1
            else:
                row.display_name = p["display_name"]
                row.auth_type = p["auth_type"]
                row.config_schema = p["config_schema"]
                row.default_field_map = p["default_field_map"]
        session.commit()
        print(f"[OK] Connector providers seeded: {added} new of {len(PROVIDERS)}")
        return added
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Error seeding connector providers: {e}")
        raise
    finally:
        session.close()
