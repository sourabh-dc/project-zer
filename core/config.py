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

# Retrieve the secret
db_name = client.get_secret("dbName").value
db_password = client.get_secret("dbPassword").value
db_host = client.get_secret("dbHost").value
db_username = client.get_secret("dbUsername").value


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

    # Security configuration
    MAX_FAILED_LOGIN_ATTEMPTS: int = Field(default=5, description="Max failed login attempts before lockout")
    ACCOUNT_LOCKOUT_MINUTES: int = Field(default=30, description="Account lockout duration in minutes")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()

SERVICE_NAME = "zeroque"
SERVICE_VERSION = "2.0.0"