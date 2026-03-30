"""AiFi integration configuration — loaded from environment variables / .env."""
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class AiFiSettings(BaseSettings):
    # Base URL for all AiFi API calls (override per environment)
    AIFI_BASE_URL: str = Field(
        default="https://api.retailer-codename.cloud.aifi.io",
        description="AiFi API base URL",
    )

    # Bearer tokens per API tier (set in .env or key vault)
    AIFI_ADMIN_TOKEN: str = Field(default="", description="Bearer token for Admin API")
    AIFI_STORE_TOKEN: str = Field(default="", description="Bearer token for Store API (on-premise)")

    # HTTP behaviour
    AIFI_TIMEOUT_SECONDS: float = Field(default=30.0, description="Per-request timeout in seconds")
    AIFI_MAX_RETRIES: int = Field(default=3, description="Max retry attempts on transient errors")
    AIFI_RETRY_BACKOFF: float = Field(default=0.5, description="Base back-off (seconds) between retries (doubles each attempt)")

    model_config = ConfigDict(env_file=".env", extra="ignore")


AIFI_SETTINGS = AiFiSettings()
