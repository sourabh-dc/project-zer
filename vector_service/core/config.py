"""
Vector Service — Configuration.

Connects to PostgreSQL (pgvector) for embeddings storage,
OpenAI (or local model) for embedding generation,
and the outbox table for event consumption.
"""
import os
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

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

class VectorSettings(BaseSettings):
    POSTGRES_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL"
    )

    AZURE_OPENAI_API_KEY: str = Field(default=azure_openai_api_key, description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default=azure_openai_endpoint, description="Azure OpenAI endpoint URL")
    AZURE_OPENAI_API_VERSION: str = Field(default=azure_openai_api_version, description="Azure OpenAI API version")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default=azure_openai_embedding_deployment, description="Azure embedding deployment name")
    EMBEDDING_DIMENSIONS: int = Field(default=1536, description="Embedding vector dimensions")

    POLL_INTERVAL_SECONDS: int = Field(default=3, description="Outbox poll interval")
    POLL_BATCH_SIZE: int = Field(default=25, description="Max events per poll cycle")

    GRAPH_SERVICE_URL: str = Field(default="http://localhost:8004", description="Graph service for approved universe")

    LOG_LEVEL: str = Field(default="INFO")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = VectorSettings()
