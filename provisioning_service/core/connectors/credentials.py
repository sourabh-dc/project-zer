"""
Credential resolution for tenant connections.

Prod: credentials live in Azure Key Vault; the connection row stores only
the secret name in ``credentials_ref``.
Local dev (ENV=local): credentials stored directly in ``credentials_enc``
JSONB — never use this in production.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from provisioning_service.Models import TenantConnection
from provisioning_service.utils.logger import logger

IS_LOCAL = os.getenv("ENV", "local").strip().lower() == "local"


def store_credentials(connection: TenantConnection, credentials: Dict[str, Any]) -> None:
    """Persist credentials onto the connection row (or Key Vault in prod)."""
    if IS_LOCAL:
        connection.credentials_enc = credentials
        connection.credentials_ref = None
        return

    # Prod path: write to Key Vault, keep only the secret name.
    from provisioning_service.core.config import SETTINGS
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    kv_name = getattr(SETTINGS, "KEYVAULT_NAME", None) or os.getenv("KEYVAULT_NAME", "").strip()
    if not kv_name:
        raise RuntimeError("KEYVAULT_NAME not configured — cannot store credentials securely")

    secret_name = f"conn-{connection.connection_id}"
    client = SecretClient(f"https://{kv_name}.vault.azure.net/", DefaultAzureCredential())
    client.set_secret(secret_name, json.dumps(credentials))
    connection.credentials_ref = secret_name
    connection.credentials_enc = None
    logger.info(f"Stored credentials for connection {connection.connection_id} in Key Vault")


def resolve_credentials(connection: TenantConnection) -> Dict[str, Any]:
    """Read credentials back out. Returns {} when none stored."""
    if connection.credentials_ref:
        from provisioning_service.core.config import SETTINGS
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        kv_name = getattr(SETTINGS, "KEYVAULT_NAME", None) or os.getenv("KEYVAULT_NAME", "").strip()
        client = SecretClient(f"https://{kv_name}.vault.azure.net/", DefaultAzureCredential())
        secret = client.get_secret(connection.credentials_ref)
        return json.loads(secret.value)

    if IS_LOCAL:
        return connection.credentials_enc or {}

    logger.warning(f"Connection {connection.connection_id} has no credentials_ref and ENV!=local")
    return {}
