"""
Data Intelligence Service — Configuration.

Connects to:
  - Azure OpenAI (LLM for text-to-query + embeddings)
  - PostgreSQL (structured data queries, outbox events, pgvector)
  - Neo4j (graph traversals, governance topology)

When ENVIRONMENT != "local", secrets are fetched from Azure Key Vault.
Otherwise, values are loaded from .env.
"""
import os

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Resolve secrets — Key Vault for deployed environments, .env for local
# ---------------------------------------------------------------------------
environment = os.getenv("ENVIRONMENT", "local").lower()

if environment != "local":
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    keyvault_name = os.getenv("KEYVAULT_NAME")
    vault_url = f"https://{keyvault_name}.vault.azure.net"
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=vault_url, credential=credential)

    def _secret(name: str, fallback: str = "") -> str:
        """Retrieve a secret from Key Vault, falling back to *fallback*."""
        try:
            value = kv_client.get_secret(name).value
            return value if value is not None else fallback
        except Exception:
            return fallback

    azure_openai_api_key = _secret("azureOpenaiApiKey")
    azure_openai_endpoint = _secret("azureOpenaiEndpoint")
    azure_openai_api_version = _secret("azureOpenaiApiVersion", "2024-06-01")
    azure_openai_llm_deployment = _secret("azureOpenaiLlmDeployment", "gpt-5-nano")
    azure_openai_embedding_deployment = _secret("azureOpenaiEmbeddingDeployment", "text-embedding-3-small")

    db_name = _secret("dbName")
    db_password = _secret("dbPassword")
    db_host = _secret("dbHost")
    db_username = _secret("dbUsername")

    neo4j_uri = _secret("neo4jUri")
    neo4j_user = _secret("neo4jUser")
    neo4j_password = _secret("neo4jPassword")
    neo4j_database = _secret("neo4jDatabase", "neo4j")

else:
    azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
    azure_openai_llm_deployment = os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT", "gpt-5-nano")
    azure_openai_embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")

    db_name = os.getenv("POSTGRES_DB")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST")
    db_username = os.getenv("POSTGRES_USER")

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

# ---------------------------------------------------------------------------
# Pydantic settings model
# ---------------------------------------------------------------------------
class DataIntelligenceSettings(BaseSettings):
    POSTGRES_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL"
    )

    AZURE_OPENAI_API_KEY: str = Field(default=azure_openai_api_key, description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default=azure_openai_endpoint, description="Azure OpenAI endpoint URL")
    AZURE_OPENAI_API_VERSION: str = Field(default=azure_openai_api_version, description="Azure OpenAI API version")
    AZURE_OPENAI_LLM_DEPLOYMENT: str = Field(default=azure_openai_llm_deployment, description="Azure chat deployment name")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default=azure_openai_embedding_deployment, description="Azure embedding deployment name")
    EMBEDDING_DIMENSIONS: int = Field(default=1536, description="Embedding vector dimensions")

    NEO4J_URI: str = Field(default=neo4j_uri, description="Neo4j bolt URI")
    NEO4J_USER: str = Field(default=neo4j_user, description="Neo4j username")
    NEO4J_PASSWORD: str = Field(default=neo4j_password, description="Neo4j password")
    NEO4J_DATABASE: str = Field(default=neo4j_database, description="Neo4j database name")

    POLL_INTERVAL_SECONDS: int = Field(default=2, description="Outbox poll interval")
    POLL_BATCH_SIZE: int = Field(default=50, description="Max events per poll cycle")
    MAX_RETRIES: int = Field(default=5, description="Max retries before dead-letter")

    LOG_LEVEL: str = Field(default="INFO")

    # Intelligence router settings
    INTELLIGENCE_API_KEY: str = Field(default="", description="API key for intelligence endpoint (empty = no auth)")
    VECTOR_SIMILARITY_THRESHOLD: float = Field(default=0.30, description="Min cosine similarity score to include vector results")
    PLAN_CACHE_TTL_SECONDS: int = Field(default=300, description="TTL in seconds for in-memory query plan cache")
    LLM_MAX_RETRIES: int = Field(default=3, description="Max retry attempts for LLM calls")
    LLM_RETRY_DELAY_SECONDS: float = Field(default=1.0, description="Base delay between LLM retries")
    SQL_QUERY_TIMEOUT_SECONDS: int = Field(default=30, description="Postgres statement timeout for LLM-generated queries")
    SQL_MAX_ROWS: int = Field(default=500, description="Max rows returned from any single SQL query")
    CYPHER_MAX_ROWS: int = Field(default=500, description="Max rows returned from any single Cypher query")

    # Redis (optional) — session memory + rate limiting
    REDIS_URL: str = Field(default="", description="Redis URL (e.g. redis://localhost:6379/0). Empty = in-memory fallback.")
    RATE_LIMIT_RPM: int = Field(default=60, description="Max requests per minute per tenant (0 = disabled)")

    model_config = ConfigDict(env_file=".env", extra="ignore")

SETTINGS = DataIntelligenceSettings()
