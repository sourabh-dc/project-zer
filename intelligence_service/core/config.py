"""
Intelligence Service — Configuration.

Connects to:
  - Azure OpenAI (LLM for text-to-query + embeddings)
  - PostgreSQL (structured data queries)
  - Neo4j (graph traversals)
  - Vector Service (semantic search)
"""
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class IntelligenceSettings(BaseSettings):
    AZURE_OPENAI_API_KEY: str = Field(default="", description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default="", description="Azure OpenAI endpoint URL")
    AZURE_OPENAI_API_VERSION: str = Field(default="2024-06-01", description="Azure OpenAI API version")
    AZURE_OPENAI_LLM_DEPLOYMENT: str = Field(default="gpt-5-nano", description="Azure chat deployment name")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default="text-embedding-3-small", description="Azure embedding deployment name")

    POSTGRES_URL: str = Field(default="", description="PostgreSQL connection URL")

    NEO4J_URI: str = Field(default="bolt://localhost:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="password")
    NEO4J_DATABASE: str = Field(default="neo4j")

    GRAPH_SERVICE_URL: str = Field(default="http://localhost:8005")
    VECTOR_SERVICE_URL: str = Field(default="http://localhost:8006")

    LOG_LEVEL: str = Field(default="INFO")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = IntelligenceSettings()
