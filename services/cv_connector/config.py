from pydantic import BaseModel
import os

class Settings(BaseModel):
    SERVICE_NAME: str = "cv_connector"
    PROVIDER: str = os.getenv("CV_PROVIDER", "aifi")

    # --- AiFi connection ---
    AIFI_BASE_URL: str = os.getenv("AIFI_BASE_URL", "https://api.aifi.example")
    AIFI_API_KEY: str = os.getenv("AIFI_API_KEY", "")

    # Optional targeting fields (if needed by AiFi tenant)
    AIFI_STORE_ID: str | None = os.getenv("AIFI_STORE_ID")
    AIFI_LOCATION_ID: str | None = os.getenv("AIFI_LOCATION_ID")

    # Paths (align to AiFi Admin API; override via env if tenant differs)
    # Create entry code (QR-ready) for a given AiFi customerId
    AIFI_PATH_ENTRY_CODES_CREATE_TMPL: str = os.getenv(
        "AIFI_PATH_ENTRY_CODES_CREATE_TMPL",
        "/api/admin/v2/customers/{customerId}/entry-codes"
    )
    # Verify entry code for a given storeId + entryId
    AIFI_PATH_ENTRY_CODES_VERIFY_TMPL: str = os.getenv(
        "AIFI_PATH_ENTRY_CODES_VERIFY_TMPL",
        "/api/admin/v2/stores/{storeId}/entry/{entryId}/entry-codes/verify"
    )
    AIFI_PATH_CUSTOMERS: str = os.getenv("AIFI_PATH_CUSTOMERS", "/api/admin/v2/customers")
    AIFI_PATH_STORES: str = os.getenv("AIFI_PATH_STORES", "/api/admin/v2/stores")
    # Product endpoints (some tenants expose upsert; otherwise fallback to POST create)
    AIFI_PATH_PRODUCTS_UPSERT: str = os.getenv("AIFI_PATH_PRODUCTS_UPSERT", "/api/admin/v2/products:upsert")
    AIFI_PATH_PRODUCTS_CREATE: str = os.getenv("AIFI_PATH_PRODUCTS_CREATE", "/api/admin/v2/products")
    # Inventory endpoint varies by tenant; keep template overrideable
    AIFI_PATH_INVENTORY_UPDATE_TMPL: str = os.getenv(
        "AIFI_PATH_INVENTORY_UPDATE_TMPL", "/api/aifi/inventory/products/{productId}"
    )

    # Our public/base URLs
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8100")
    CV_GATEWAY_BASE_URL: str = os.getenv("CV_GATEWAY_BASE_URL", "http://localhost:8000")

    # Security
    DEV_JWT_SECRET: str = os.getenv("DEV_JWT_SECRET", "")
    # If not explicitly set, default webhook secret to DEV_JWT_SECRET for dev convenience
    WEBHOOK_SHARED_SECRET: str = os.getenv("WEBHOOK_SHARED_SECRET", "") or os.getenv("DEV_JWT_SECRET", "")
    REQUIRE_IDEMPOTENCY: bool = True

settings = Settings()