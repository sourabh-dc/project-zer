from typing import Optional
import os
from dotenv import load_dotenv
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings

# Load environment variables from .env file
load_dotenv()

environment = os.getenv("ENVIRONMENT", "Local")

# Prefer env vars directly; skip Key Vault for Local/Development
if environment.lower() in ["local", "development", "dev"]:
    db_name = os.getenv("POSTGRES_DB", "zeroque_dev_sync")
    db_password = os.getenv("POSTGRES_PASSWORD", "")
    db_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    db_username = os.getenv("POSTGRES_USER", os.getenv("USER", "sourabhagrawal"))
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY", "dummy")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "dummy")
else:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    keyvault_name = os.getenv("KEYVAULT_NAME")
    if not keyvault_name:
        raise RuntimeError("KEYVAULT_NAME not set for non-local environment")
    vault_url = f"https://{keyvault_name}.vault.azure.net"
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    db_name = client.get_secret("dbName").value
    db_password = client.get_secret("dbPassword").value
    db_host = client.get_secret("dbHost").value
    db_username = client.get_secret("dbUsername").value
    stripe_secret_key = client.get_secret("stripeSecretKey").value
    stripe_webhook_secret = client.get_secret("stripeWebhookSecret").value


class Settings(BaseSettings):
    """Application settings - simple and powerful"""
    DATABASE_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL"
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching"
    )
    JWT_ISSUER: str = Field(default="http://mock-idp", description="JWT issuer (IdP)")
    JWT_AUDIENCE: str = Field(default="zeroque-api", description="JWT audience")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    JWT_SECRET: Optional[str] = Field(default="mock-secret", description="JWT shared secret for HS algorithms")
    JWT_JWKS_URL: Optional[str] = Field(default=None, description="JWKS endpoint for RSA/EC algorithms")
    JWT_CACHE_SECONDS: int = Field(default=300, description="How long to cache JWKS keys")
    PORT: int = Field(default=80, description="Service port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    BOOTSTRAP_ADMIN_EMAIL: str = Field(default="admin@zeroque.local", description="Bootstrap admin email")
    BOOTSTRAP_ADMIN_API_KEY: str = Field(default="zq_bootstrap_admin_key", description="Bootstrap admin API key")
    BOOTSTRAP_TENANT_NAME: str = Field(default="ZeroQue Bootstrap Tenant", description="Bootstrap tenant name")

    # Production configuration
    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30
    API_KEY_EXPIRY_DAYS: int = 90
    CACHE_TTL_SECONDS: int = 300  # 5 minutes

    # Authentication settings
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 30

    #Stripe settings
    STRIPE_SECRET_KEY: str = stripe_secret_key
    STRIPE_WEBHOOK_SECRET: str = stripe_webhook_secret

    # AiFi integration settings
    AIFI_BASE_URL: str = Field(default=os.getenv("AIFI_BASE_URL", "https://oasis-api.27-12.oasis.aifi.com"))
    AIFI_API_KEY: str = Field(default=os.getenv("AIFI_API_KEY", ""))
    AIFI_STORE_ID: str = Field(default=os.getenv("AIFI_STORE_ID", ""))
    AIFI_LOCATION_ID: str = Field(default=os.getenv("AIFI_LOCATION_ID", ""))

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()
print(SETTINGS.DATABASE_URL)
SERVICE_NAME = "zeroque"
SERVICE_VERSION = "2.0.0"