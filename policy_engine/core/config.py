"""
Policy Engine Configuration
Environment-based settings for the Policy Engine service
"""
import os

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from pydantic import Field
from pydantic_settings import BaseSettings
from functools import lru_cache

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

environment = os.getenv("ENVIRONMENT", "Development")
# Retrieve the secret
if environment == "Development":
    db_name = client.get_secret("dbName").value
    db_password = client.get_secret("dbPassword").value
    db_host = client.get_secret("dbHost").value
    db_username = client.get_secret("dbUsername").value
    email_conn_string = client.get_secret("azure-email").value
else:
    db_name = os.getenv("POSTGRES_DB")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST")
    db_username = os.getenv("POSTGRES_USER")
    email_conn_string = os.getenv("AZURE_EMAIL_CONNECTION_STRING")


class Settings(BaseSettings):
    """Application settings - simple and powerful"""
    DATABASE_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL"
    )
    
    # Redis (for caching policies)
    REDIS_URL: str = "redis://localhost:6379/1"  # Use DB 1 for policy engine
    
    # Service
    SERVICE_NAME: str = "policy-engine"
    SERVICE_VERSION: str = "1.0.0"
    PORT: int = 8004
    LOG_LEVEL: str = "INFO"
    
    # CORS
    ALLOW_ORIGINS: str = "*"
    
    # Database Pool
    CONNECTION_POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 5
    POOL_TIMEOUT: int = 30
    POOL_RECYCLE: int = 3600
    
    # Cache settings
    POLICY_CACHE_TTL_SECONDS: int = 300  # 5 minutes
    DECISION_LOG_RETENTION_DAYS: int = 90  # 3 months
    
    # JWT Settings (for auth)
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_JWKS_URL: str = ""
    JWT_AUDIENCE: str = ""
    JWT_ISSUER: str = ""
    JWT_EXPIRY_MINUTES: int = 60
    JWT_CACHE_SECONDS: int = 3600
    
    # Feature flags
    ENABLE_DECISION_LOGGING: bool = True
    ENABLE_METRICS: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


SETTINGS = get_settings()
