from typing import Optional
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Get values from environment
keyvault_name = os.getenv("KEYVAULT_NAME")
vault_url = f"https://{keyvault_name}.vault.azure.net"

# Authenticate using App Registration credentials
credential = DefaultAzureCredential()
client = SecretClient(vault_url=vault_url, credential=credential)

environment = os.getenv("ENVIRONMENT")
# Retrieve the secret
if environment != "local":
    db_name = client.get_secret("dbName").value
    db_password = client.get_secret("dbPassword").value
    db_host = client.get_secret("dbHost").value
    db_username = client.get_secret("dbUsername").value
    stripe_secret_key = client.get_secret("stripeSecretKey").value
    stripe_webhook_secret = client.get_secret("stripeWebhookSecret").value
    email_conn_string = client.get_secret("azure-email").value
else:
    db_name = os.getenv("POSTGRES_DB")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST")
    db_username = os.getenv("POSTGRES_USER")
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    email_conn_string = os.getenv("AZURE_EMAIL_CONNECTION_STRING")


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

    SB_NAMESPACE: str = "zeroque.servicebus.windows.net"
    QUEUE_NAME: str = "outbox-task-queue"

    # Policy Engine integration
    POLICY_ENGINE_URL: str = Field(default="http://localhost:8004", description="Policy Engine base URL")
    POLICY_EVALUATE_TIMEOUT: float = Field(default=5.0, description="Timeout in seconds for policy evaluation calls")

    EMAIL_CONNECTION_STRING: str = email_conn_string

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()
print(SETTINGS.DATABASE_URL)
SERVICE_NAME = "zeroque"
SERVICE_VERSION = "2.0.0"