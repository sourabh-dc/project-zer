from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from pathlib import Path


class IntegrationSettings(BaseSettings):
    """Vendor-agnostic integration settings (loaded from integrations/.env)."""

    AIFI_BASE_URL: str = Field(default="https://oasis-api.27-12.oasis.aifi.com")
    AIFI_API_KEY: str = Field(default="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzaG9wIjoiY29uc3VtYWJsZXMtZ2IiLCJ0b2tlblR5cGUiOiJBRE1JTiIsImlhdCI6MTc0ODQ1MTk4Nn0.aR81DfOnjtCOIq0spJiGGj0jmj_BTUQcz3jlQy37SMc")
    AIFI_STORE_ID: str = Field(default="consumables-gb")
    AIFI_LOCATION_ID: str = Field(default="1")

    class Config:
        env_file = Path(__file__).resolve().parent / ".env"
        extra = "ignore"


@lru_cache()
def get_integration_settings() -> IntegrationSettings:
    return IntegrationSettings()


INTEGRATION_SETTINGS = get_integration_settings()

