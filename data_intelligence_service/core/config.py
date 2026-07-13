"""
ZeroQue Data Intelligence Service — Configuration
==================================================
Sensitive values → Key Vault in production, .env locally.
Non-sensitive values → environment variables always.
"""
import os
import logging
from typing import Optional

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

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
    env = os.getenv("ENVIRONMENT", "local").strip().lower()
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

_OPENAI_KEY        = _secret("azureOpenaiApiKey",             "AZURE_OPENAI_API_KEY",              "")
_OPENAI_ENDPOINT   = _secret("azureOpenaiEndpoint",           "AZURE_OPENAI_ENDPOINT",             "")
_OPENAI_API_VER    = _secret("azureOpenaiApiVersion",         "AZURE_OPENAI_API_VERSION",          "2024-06-01")
_OPENAI_LLM_DEP    = _secret("azureOpenaiLlmDeployment",      "AZURE_OPENAI_LLM_DEPLOYMENT",       "gpt-5-nano")
_OPENAI_EMBED_DEP  = _secret("azureOpenaiEmbeddingDeployment","AZURE_OPENAI_EMBEDDING_DEPLOYMENT",  "text-embedding-3-small")

_NEO4J_URI      = _secret("neo4jUri",      "NEO4J_URI",      "bolt://localhost:7687")
_NEO4J_USER     = _secret("neo4jUser",     "NEO4J_USER",     "neo4j")
_NEO4J_PASSWORD = _secret("neo4jPassword", "NEO4J_PASSWORD", "password")
_NEO4J_DATABASE = _secret("neo4jDatabase", "NEO4J_DATABASE", "neo4j")

_INTELLIGENCE_API_KEY = _secret("intelligenceApiKey", "INTELLIGENCE_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════════════════════════════

class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default=f"postgresql://{_DB_USER}:{_DB_PASSWORD}@{_DB_HOST}:5432/{_DB_NAME}",
        description="PostgreSQL connection URL",
    )
    # Legacy alias — some modules still reference POSTGRES_URL
    POSTGRES_URL: str = Field(
        default=f"postgresql://{_DB_USER}:{_DB_PASSWORD}@{_DB_HOST}:5432/{_DB_NAME}",
        description="PostgreSQL connection URL (legacy alias for DATABASE_URL)",
    )
    CONNECTION_POOL_SIZE: int = 20
    MAX_OVERFLOW: int = 10
    POOL_TIMEOUT: int = 30

    # ── Azure OpenAI ──────────────────────────────────────────────
    AZURE_OPENAI_API_KEY: str = Field(default=_OPENAI_KEY, description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default=_OPENAI_ENDPOINT, description="Azure OpenAI endpoint URL")
    AZURE_OPENAI_API_VERSION: str = Field(default=_OPENAI_API_VER, description="Azure OpenAI API version")
    AZURE_OPENAI_LLM_DEPLOYMENT: str = Field(default=_OPENAI_LLM_DEP, description="Azure chat deployment name")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default=_OPENAI_EMBED_DEP, description="Azure embedding deployment name")
    EMBEDDING_DIMENSIONS: int = Field(default=1536, description="Embedding vector dimensions")

    # ── Neo4j ─────────────────────────────────────────────────────
    NEO4J_URI: str = Field(default=_NEO4J_URI, description="Neo4j bolt URI")
    NEO4J_USER: str = Field(default=_NEO4J_USER, description="Neo4j username")
    NEO4J_PASSWORD: str = Field(default=_NEO4J_PASSWORD, description="Neo4j password")
    NEO4J_DATABASE: str = Field(default=_NEO4J_DATABASE, description="Neo4j database name")

    # ── Service ───────────────────────────────────────────────────
    PORT: int = 80
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Intelligence ──────────────────────────────────────────────
    INTELLIGENCE_API_KEY: str = Field(default=_INTELLIGENCE_API_KEY, description="API key for intelligence endpoint")
    VECTOR_SIMILARITY_THRESHOLD: float = Field(default=0.30, description="Min cosine similarity score to include vector results")
    PLAN_CACHE_TTL_SECONDS: int = Field(default=300, description="TTL in seconds for in-memory query plan cache")
    LLM_MAX_RETRIES: int = Field(default=3, description="Max retry attempts for LLM calls")
    LLM_RETRY_DELAY_SECONDS: float = Field(default=1.0, description="Base delay between LLM retries")
    SQL_QUERY_TIMEOUT_SECONDS: int = Field(default=30, description="Postgres statement timeout for LLM-generated queries")
    SQL_MAX_ROWS: int = Field(default=500, description="Max rows returned from any single SQL query")
    CYPHER_MAX_ROWS: int = Field(default=500, description="Max rows returned from any single Cypher query")

    # ── Outbox Consumer ───────────────────────────────────────────
    POLL_INTERVAL_SECONDS: int = Field(default=2, description="Outbox poll interval")
    POLL_BATCH_SIZE: int = Field(default=50, description="Max events per poll cycle")
    MAX_RETRIES: int = Field(default=5, description="Max retries before dead-letter")

    # ── Redis (optional) — session memory + rate limiting ─────────
    REDIS_URL: str = Field(default="", description="Redis URL (e.g. redis://localhost:6379/0). Empty = in-memory fallback.")
    RATE_LIMIT_RPM: int = Field(default=60, description="Max requests per minute per tenant (0 = disabled)")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = Settings()
SERVICE_NAME = "data_intelligence_service"
SERVICE_VERSION = "0.3.0"
