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


class VectorSettings(BaseSettings):
    POSTGRES_URL: str = Field(default="", description="PostgreSQL URL (shared DB with pgvector extension)")

    AZURE_OPENAI_API_KEY: str = Field(default="", description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default="", description="Azure OpenAI endpoint URL")
    AZURE_OPENAI_API_VERSION: str = Field(default="2024-06-01", description="Azure OpenAI API version")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default="text-embedding-3-small", description="Azure embedding deployment name")
    EMBEDDING_DIMENSIONS: int = Field(default=1536, description="Embedding vector dimensions")

    POLL_INTERVAL_SECONDS: int = Field(default=3, description="Outbox poll interval")
    POLL_BATCH_SIZE: int = Field(default=25, description="Max events per poll cycle")

    GRAPH_SERVICE_URL: str = Field(default="http://localhost:8005", description="Graph service for approved universe")

    LOG_LEVEL: str = Field(default="INFO")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = VectorSettings()
