"""
ZeroQue Provisioning Service — Configuration
=============================================
Sensitive values → Key Vault in production, .env locally.
Non-sensitive values → environment variables always.
"""
from typing import Optional
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os
import logging

load_dotenv()
logger = logging.getLogger("config")

# ═══════════════════════════════════════════════════════════════════
# Secret helper — Key Vault (cloud) or env var (local)
# ═══════════════════════════════════════════════════════════════════

_keyvault_client = None
_keyvault_available = False


def _init_keyvault():
    """Initialise Key Vault client if KEYVAULT_NAME is configured and we're not local."""
    global _keyvault_client, _keyvault_available
    kv_name = os.getenv("KEYVAULT_NAME", "").strip()
    env = os.getenv("ENVIRONMENT").strip().lower()
    print(env, kv_name)
    if not kv_name or env == "local":
        _keyvault_available = False
        return

    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
        vault_url = f"https://{kv_name}.vault.azure.net"
        credential = DefaultAzureCredential()
        _keyvault_client = SecretClient(vault_url=vault_url, credential=credential)
        _keyvault_available = True
        logger.info(f"Key Vault client initialised: {kv_name}")
    except Exception as e:
        logger.warning(f"Key Vault unavailable, falling back to env vars: {e}")
        _keyvault_available = False


def _secret(keyvault_name: str, env_var: str, default: str = "") -> str:
    """Fetch a secret: Key Vault (if available) → env var → default."""
    # Try Key Vault first
    if _keyvault_available and _keyvault_client:
        try:
            secret = _keyvault_client.get_secret(keyvault_name)
            if secret and secret.value:
                return secret.value
        except Exception:
            pass  # fall through to env var

    # Fall back to environment variable
    val = os.getenv(env_var, "")
    if val:
        return val

    return default


# Init Key Vault on module load
_init_keyvault()

# ═══════════════════════════════════════════════════════════════════
# Secrets (Key Vault names, env-var fallback keys, defaults)
# ═══════════════════════════════════════════════════════════════════

_DB_NAME     = _secret("dbName",              "POSTGRES_DB",                 "")
_DB_USER     = _secret("dbUsername",          "POSTGRES_USER",               "")
_DB_PASSWORD = _secret("dbPassword",          "POSTGRES_PASSWORD",           "")
_DB_HOST     = _secret("dbHost",              "POSTGRES_HOST",               "")
_JWT_SECRET  = _secret("jwt-secret",          "JWT_SECRET",                  "mock-secret")
_STRIPE_SK   = _secret("stripeSecretKey",     "STRIPE_SECRET_KEY",           "")
_STRIPE_WH   = _secret("stripeWebhookSecret", "STRIPE_WEBHOOK_SECRET",       "")
_EMAIL_CS    = _secret("azure-email",         "AZURE_EMAIL_CONNECTION_STRING","")
_AIFI_KEY    = _secret("aifi-api-key",        "AIFI_API_KEY",                "")
_SB_CONN     = _secret("service-bus-connection", "SERVICE_BUS_CONNECTION_STRING", "")
_CH_API_KEY  = _secret("companies-house-api-key", "COMPANIES_HOUSE_API_KEY",     "")
_GOOGLE_KEY  = _secret("google-maps-api-key",   "GOOGLE_MAPS_API_KEY",         "")

# ═══════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════

class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default=f"postgresql://{_DB_USER}:{_DB_PASSWORD}@{_DB_HOST}:5432/{_DB_NAME}",
        description="PostgreSQL connection URL",
    )
    print(f"Database URL: {DATABASE_URL}")
    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        description="Redis connection URL",
    )

    # ── JWT ───────────────────────────────────────────────────────
    JWT_SECRET: str = Field(default=_JWT_SECRET, description="JWT signing secret")
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    JWT_ISSUER: str = Field(default=os.getenv("JWT_ISSUER", "http://mock-idp"))
    JWT_AUDIENCE: str = Field(default=os.getenv("JWT_AUDIENCE", "zeroque-api"))
    JWT_JWKS_URL: Optional[str] = Field(default=os.getenv("JWT_JWKS_URL"))
    JWT_CACHE_SECONDS: int = 300
    JWT_EXPIRY_MINUTES: int = 60
    REFRESH_TOKEN_DAYS: int = 30

    # ── Service ───────────────────────────────────────────────────
    PORT: int = 80
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # ── Stripe ────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = _STRIPE_SK
    STRIPE_WEBHOOK_SECRET: str = _STRIPE_WH
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

    # ── Email ─────────────────────────────────────────────────────
    EMAIL_CONNECTION_STRING: str = _EMAIL_CS

    # ── AiFi Integration ──────────────────────────────────────────
    AIFI_BASE_URL: str = os.getenv("AIFI_BASE_URL", "https://oasis-api.27-12.oasis.aifi.com")
    AIFI_API_KEY: str = _AIFI_KEY
    AIFI_STORE_ID: str = os.getenv("AIFI_STORE_ID", "")
    AIFI_LOCATION_ID: str = os.getenv("AIFI_LOCATION_ID", "")

    # ── Companies House ───────────────────────────────────────────
    COMPANIES_HOUSE_API_KEY: str = _CH_API_KEY
    COMPANIES_HOUSE_BASE_URL: str = os.getenv(
        "COMPANIES_HOUSE_BASE_URL", "https://api.company-information.service.gov.uk"
    )

    # ── Google Maps / Places ──────────────────────────────────────
    GOOGLE_MAPS_API_KEY: str = _GOOGLE_KEY
    GOOGLE_MAPS_BASE_URL: str = os.getenv(
        "GOOGLE_MAPS_BASE_URL", "https://maps.googleapis.com/maps/api"
    )

    # ── Service Bus ───────────────────────────────────────────────
    SB_NAMESPACE: str = os.getenv("SB_NAMESPACE", "zeroque.servicebus.windows.net")
    QUEUE_NAME: str = os.getenv("QUEUE_NAME", "provisioning-outbox-queue")

    # ── OPA / Policy Engine ───────────────────────────────────────
    OPA_URL: str = os.getenv("OPA_URL", "http://localhost:8181")
    POLICY_ENGINE_BYPASS: bool = Field(
        default=os.getenv("POLICY_ENGINE_BYPASS", "false").lower() == "true",
    )

    # ── Azure AD / CIAM ───────────────────────────────────────────
    AZURE_AD_TENANT_ID: Optional[str] = Field(default=os.getenv("AZURE_AD_TENANT_ID"))
    AZURE_AD_CLIENT_ID: Optional[str] = Field(default=os.getenv("AZURE_AD_CLIENT_ID"))
    AZURE_AD_SPA_CLIENT_ID: Optional[str] = Field(default=os.getenv("AZURE_AD_SPA_CLIENT_ID"))
    AZURE_AD_CIAM: bool = Field(
        default=os.getenv("AZURE_AD_CIAM", "true").lower() == "true",
    )
    AZURE_AD_CIAM_HOSTNAME: Optional[str] = Field(default=os.getenv("AZURE_AD_CIAM_HOSTNAME"))
    # Legacy B2C
    AZURE_AD_B2C_TENANT: Optional[str] = Field(default=os.getenv("AZURE_AD_B2C_TENANT"))
    AZURE_AD_B2C_CLIENT_ID: Optional[str] = Field(default=os.getenv("AZURE_AD_B2C_CLIENT_ID"))
    AZURE_AD_B2C_POLICY: Optional[str] = Field(default=os.getenv("AZURE_AD_B2C_POLICY"))

    # ── Bootstrap ─────────────────────────────────────────────────
    BOOTSTRAP_ADMIN_EMAIL: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@zeroque.local")
    BOOTSTRAP_ADMIN_API_KEY: str = os.getenv("BOOTSTRAP_ADMIN_API_KEY", "zq_bootstrap_admin_key")
    BOOTSTRAP_TENANT_NAME: str = os.getenv("BOOTSTRAP_TENANT_NAME", "ZeroQue Bootstrap Tenant")

    # ── Misc ──────────────────────────────────────────────────────
    API_KEY_EXPIRY_DAYS: int = 90
    CACHE_TTL_SECONDS: int = 300
    PAYMENT_GRACE_PERIOD_DAYS: int = 3
    PASSWORD_RESET_EXPIRY_MINUTES: int = 60
    OTP_EXPIRY_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 3

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()
SERVICE_NAME = "zeroque"
SERVICE_VERSION = "2.0.0"
