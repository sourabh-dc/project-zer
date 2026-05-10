import os

from dotenv import load_dotenv
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings

load_dotenv()

environment = os.getenv("ENVIRONMENT", "local").lower()

if environment != "local":
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    keyvault_name = os.getenv("KEYVAULT_NAME")
    vault_url = f"https://{keyvault_name}.vault.azure.net"
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    def _secret(name: str, fallback: str = "") -> str:
        try:
            value = kv_client.get_secret(name).value
            return value if value is not None else fallback
        except Exception:
            return fallback

    db_name = _secret("dbName")
    db_password = _secret("dbPassword")
    db_host = _secret("dbHost")
    db_username = _secret("dbUsername")
else:
    db_name = os.getenv("POSTGRES_DB")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST")
    db_username = os.getenv("POSTGRES_USER")


class Settings(BaseSettings):
    DATABASE_URL: str = Field(
        default=(
            os.getenv("DATABASE_URL")
            or f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}"
        ),
        description="PostgreSQL connection URL",
    )
    print(f"Using DATABASE_URL: {DATABASE_URL}")
    PORT: int = Field(default=8008, description="Orders service port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    JWT_ISSUER: str = Field(default="http://mock-idp")
    JWT_AUDIENCE: str = Field(default="zeroque-api")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_SECRET: str = Field(default="mock-secret")
    JWT_CACHE_SECONDS: int = Field(default=300)
    JWT_EXPIRY_MINUTES: int = Field(default=60)

    # Policy enforcement (OPA Rego evaluated in-process via shared/policy_engine)
    POLICY_ENGINE_BYPASS: bool = Field(default=False)

    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30

    SB_NAMESPACE: str = Field(default="zeroque.servicebus.windows.net")
    QUEUE_NAME: str = Field(default="outbox-task-queue")
    EMAIL_CONNECTION_STRING: str = Field(default=os.getenv("AZURE_EMAIL_CONNECTION_STRING", ""))
    EMAIL_SENDER_ADDRESS: str = Field(default=os.getenv("EMAIL_SENDER_ADDRESS", "DoNotReply@zeroque.com"))
    ORDERS_BASE_URL: str = Field(default=os.getenv("ORDERS_BASE_URL", "http://localhost:8008"))

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()