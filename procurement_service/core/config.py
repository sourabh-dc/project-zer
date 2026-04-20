from typing import Optional
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    DATABASE_URL: str = Field(default="sqlite:///./procurement_service.db", description="Database connection URL")
    PORT: int = Field(default=8011, description="Service port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    AUTH_MODE: str = Field(default="header", description="header|jwt")
    JWT_ISSUER: str = Field(default="procurement-service", description="JWT issuer")
    JWT_AUDIENCE: str = Field(default="procurement-api", description="JWT audience")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    JWT_SECRET: Optional[str] = Field(default="local-procurement-secret", description="JWT secret")

    # Policy enforcement (OPA Rego evaluated in-process via shared/policy_engine)
    POLICY_ENGINE_BYPASS: bool = Field(default=False, description="When True, skip policy checks (dev only)")
    INTERNAL_API_KEY: str = Field(default="local-internal-key", description="Internal maintenance API key")
    APP_BASE_URL: str = Field(default="http://localhost:9001", description="Base URL used in outbound action links")

    EMAIL_PROVIDER: str = Field(default="azure_communication", description="azure_communication|disabled")
    AZURE_COMMUNICATION_CONNECTION_STRING: Optional[str] = Field(default=None, description="Azure Communication Services connection string")
    AZURE_COMMUNICATION_SENDER: Optional[str] = Field(default=None, description="Azure Communication Services verified sender address")
    EMAIL_DRY_RUN: bool = Field(default=True, description="If true, skip external provider calls and mark delivery as simulated")

    CORS_ALLOW_ORIGINS: str = Field(default="*", description="Comma separated CORS origins")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()
SERVICE_NAME = "procurement_service"
SERVICE_VERSION = "1.0.0"
