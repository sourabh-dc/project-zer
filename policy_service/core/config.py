"""
Policy Engine — standalone configuration.

Reads DB credentials from Azure Key Vault (Development) or environment
variables (Production). Fully independent of provisioning_service.
"""
from typing import Optional
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv
import os

load_dotenv()

# --- Key Vault / env bootstrap ---
keyvault_name = os.getenv("KEYVAULT_NAME")
vault_url = f"https://{keyvault_name}.vault.azure.net"

credential = DefaultAzureCredential()
kv_client = SecretClient(vault_url=vault_url, credential=credential)

environment = os.getenv("ENVIRONMENT")

if environment != "local":
    db_name = kv_client.get_secret("dbName").value
    db_password = kv_client.get_secret("dbPassword").value
    db_host = kv_client.get_secret("dbHost").value
    db_username = kv_client.get_secret("dbUsername").value
else:
    db_name = os.getenv("POSTGRES_DB")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST")
    db_username = os.getenv("POSTGRES_USER")


class PolicySettings(BaseSettings):
    """Policy Engine settings"""

    DATABASE_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL",
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching",
    )
    PORT: int = Field(default=8004, description="Service port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Connection pool
    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = PolicySettings()

SERVICE_NAME = "policy-engine"
SERVICE_VERSION = "1.0.0"

