from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = Field(
        default="postgresql://zeroque:zeroque_dev_password@localhost:5432/zeroque_dev",
        description="PostgreSQL connection URL",
    )
    PORT: int = Field(default=8008, description="Orders service port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    JWT_ISSUER: str = Field(default="http://mock-idp")
    JWT_AUDIENCE: str = Field(default="zeroque-api")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_SECRET: str = Field(default="mock-secret")
    JWT_CACHE_SECONDS: int = Field(default=300)
    JWT_EXPIRY_MINUTES: int = Field(default=60)

    POLICY_ENGINE_URL: str = Field(default="http://localhost:8004")
    POLICY_EVALUATE_TIMEOUT: float = Field(default=5.0)

    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()

