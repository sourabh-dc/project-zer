"""
Intelligence Service — Configuration.

Connects to:
  - Azure OpenAI (LLM for text-to-query + embeddings)
  - PostgreSQL (structured data queries)
  - Neo4j (graph traversals)
  - Vector Service (semantic search)

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
    stripe_secret_key = _secret("stripeSecretKey")
    stripe_webhook_secret = _secret("stripeWebhookSecret")
    email_conn_string = _secret("azure-email")

    neo4j_uri = _secret("neo4jUri", "bolt://localhost:7687")
    neo4j_user = _secret("neo4jUser", "neo4j")
    neo4j_password = _secret("neo4jPassword", "password")
    neo4j_database = _secret("neo4jDatabase", "neo4j")

    graph_service_url = _secret("graphServiceUrl", "http://localhost:8005")
    vector_service_url = _secret("vectorServiceUrl", "http://localhost:8006")
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
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    email_conn_string = os.getenv("AZURE_EMAIL_CONNECTION_STRING")

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    graph_service_url = os.getenv("GRAPH_SERVICE_URL", "http://localhost:8005")
    vector_service_url = os.getenv("VECTOR_SERVICE_URL", "http://localhost:8006")


# ---------------------------------------------------------------------------
# Pydantic settings model
# ---------------------------------------------------------------------------
class IntelligenceSettings(BaseSettings):

    POSTGRES_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL"
    )

    AZURE_OPENAI_API_KEY: str = Field(default=azure_openai_api_key, description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default=azure_openai_endpoint, description="Azure OpenAI endpoint URL")
    AZURE_OPENAI_API_VERSION: str = Field(default=azure_openai_api_version, description="Azure OpenAI API version")
    AZURE_OPENAI_LLM_DEPLOYMENT: str = Field(default=azure_openai_llm_deployment, description="Azure chat deployment name")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default=azure_openai_embedding_deployment, description="Azure embedding deployment name")

    NEO4J_URI: str = Field(default=neo4j_uri)
    NEO4J_USER: str = Field(default=neo4j_user)
    NEO4J_PASSWORD: str = Field(default=neo4j_password)
    NEO4J_DATABASE: str = Field(default=neo4j_database)

    GRAPH_SERVICE_URL: str = Field(default=graph_service_url)
    VECTOR_SERVICE_URL: str = Field(default=vector_service_url)

    LOG_LEVEL: str = Field(default="INFO")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = IntelligenceSettings()
