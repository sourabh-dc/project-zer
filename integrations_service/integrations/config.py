from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from pathlib import Path


class IntegrationSettings(BaseSettings):
    """Vendor-agnostic integration settings (loaded from integrations/.env)."""

    AIFI_BASE_URL: str = Field(default="")
    AIFI_API_KEY: str = Field(default="")
    AIFI_STORE_ID: str = Field(default="")
    AIFI_LOCATION_ID: str = Field(default="")

    class Config:
        env_file = Path(__file__).resolve().parent / ".env"
        extra = "ignore"


@lru_cache()
def get_integration_settings() -> IntegrationSettings:
    return IntegrationSettings()


INTEGRATION_SETTINGS = get_integration_settings()

