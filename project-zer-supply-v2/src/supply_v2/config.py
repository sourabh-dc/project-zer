from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    broker_backend: str = "database"
    email_backend: str = "console"
    auth_mode: str = "header"
    policy_mode: str = "local"
    opa_url: str = "http://localhost:8181"
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_authority: str = "https://login.microsoftonline.com"
    entra_jwks_url: str = ""
    azure_service_bus_connection_string: str = ""
    azure_service_bus_queue_name: str = "supply-notifications"
    azure_email_connection_string: str = ""
    azure_email_sender: str = ""
    jwt_secret: str = ""
    jwt_audience: str = "supply-v2"
    jwt_issuer: str = "supply-v2"
    internal_api_key: str = "local-internal-key"
    applicationinsights_connection_string: str = ""


def get_settings() -> Settings:
    return Settings(
        broker_backend=os.environ.get("SUPPLY_V2_BROKER_BACKEND", "database"),
        email_backend=os.environ.get("SUPPLY_V2_EMAIL_BACKEND", "console"),
        auth_mode=os.environ.get("SUPPLY_V2_AUTH_MODE", "header"),
        policy_mode=os.environ.get("SUPPLY_V2_POLICY_MODE", "local"),
        opa_url=os.environ.get("OPA_URL", "http://localhost:8181"),
        entra_tenant_id=os.environ.get("SUPPLY_V2_ENTRA_TENANT_ID", ""),
        entra_client_id=os.environ.get("SUPPLY_V2_ENTRA_CLIENT_ID", ""),
        entra_authority=os.environ.get("SUPPLY_V2_ENTRA_AUTHORITY", "https://login.microsoftonline.com"),
        entra_jwks_url=os.environ.get("SUPPLY_V2_ENTRA_JWKS_URL", ""),
        azure_service_bus_connection_string=os.environ.get("AZURE_SERVICE_BUS_CONNECTION_STRING", ""),
        azure_service_bus_queue_name=os.environ.get("AZURE_SERVICE_BUS_QUEUE_NAME", "supply-notifications"),
        azure_email_connection_string=os.environ.get("AZURE_EMAIL_CONNECTION_STRING", ""),
        azure_email_sender=os.environ.get("AZURE_EMAIL_SENDER", ""),
        jwt_secret=os.environ.get("SUPPLY_V2_JWT_SECRET", ""),
        jwt_audience=os.environ.get("SUPPLY_V2_JWT_AUDIENCE", "supply-v2"),
        jwt_issuer=os.environ.get("SUPPLY_V2_JWT_ISSUER", "supply-v2"),
        internal_api_key=os.environ.get("SUPPLY_V2_INTERNAL_API_KEY", "local-internal-key"),
        applicationinsights_connection_string=os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", ""),
    )
