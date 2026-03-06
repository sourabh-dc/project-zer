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


class GraphSettings(BaseSettings):
    NEO4J_URI: str = Field(default="bolt://localhost:7687", description="Neo4j bolt URI")
    NEO4J_USER: str = Field(default="neo4j", description="Neo4j username")
    NEO4J_PASSWORD: str = Field(default="password", description="Neo4j password")
    NEO4J_DATABASE: str = Field(default="neo4j", description="Neo4j database name")

    POSTGRES_URL: str = Field(default="", description="PostgreSQL URL for outbox polling")

    POLL_INTERVAL_SECONDS: int = Field(default=2, description="Outbox poll interval")
    POLL_BATCH_SIZE: int = Field(default=50, description="Max events per poll cycle")
    MAX_RETRIES: int = Field(default=5, description="Max retries before dead-letter")

    LOG_LEVEL: str = Field(default="INFO")

    model_config = ConfigDict(env_file=".env", extra="ignore")


SETTINGS = GraphSettings()
