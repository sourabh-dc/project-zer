from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings():
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/zeroque_dev"
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672//"
    REDIS_URL: str = "redis://localhost:6379/0"
    SUBSCRIPTIONS_SERVICE_URL: str = "http://localhost:8010"
    JWT_SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    ALLOW_DEMO: bool = False
    SERVICE_PORT: int = 8000
    ENVIRONMENT: str = "development"

    model_config = ConfigDict(env_file=".env", extra="ignore")

def get_settings() -> Settings:
    return Settings()