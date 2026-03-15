"""
Graph Service — Configuration.

Connects to Neo4j for governance topology projection and
PostgreSQL for outbox event consumption.
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

    db_name = _secret("dbName")
    db_password = _secret("dbPassword")
    db_host = _secret("dbHost")
    db_username = _secret("dbUsername")
    neo4j_password = _secret("neo4jPassword")
    neo4j_uri = _secret("neo4jUri")
    neo4j_user = _secret("neo4jUser")

else:
    db_name = os.getenv("POSTGRES_DB")
    db_password = os.getenv("POSTGRES_PASSWORD")
    db_host = os.getenv("POSTGRES_HOST")
    db_username = os.getenv("POSTGRES_USER")
    neo4j_password = os.getenv("NEO4J_USER")
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_PASSWORD")

class GraphSettings(BaseSettings):
    NEO4J_URI: str = Field(default=neo4j_uri, description="Neo4j bolt URI")
    NEO4J_USER: str = Field(default=neo4j_user, description="Neo4j username")
    NEO4J_PASSWORD: str = Field(default=neo4j_password, description="Neo4j password")
    NEO4J_DATABASE: str = Field(default="neo4j", description="Neo4j database name")

    POSTGRES_URL: str = Field(
        default=f"postgresql://{db_username}:{db_password}@{db_host}:5432/{db_name}",
        description="PostgreSQL connection URL"
    )

    POLL_INTERVAL_SECONDS: int = Field(default=2, description="Outbox poll interval")
    POLL_BATCH_SIZE: int = Field(default=50, description="Max events per poll cycle")
    MAX_RETRIES: int = Field(default=5, description="Max retries before dead-letter")

    LOG_LEVEL: str = Field(default="INFO")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = GraphSettings()
