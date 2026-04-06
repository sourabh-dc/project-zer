"""
Centralised configuration — loaded from environment variables / .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv()

POSTGRES_URL: str = os.getenv(
    "POSTGRES_URL",
    "postgresql://zeroque:zeroque_dev_password@localhost:5433/zeroque_events",
)

NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "neo4j_dev_password")

SERVICE_BUS_CONNECTION: str = os.getenv("SERVICE_BUS_CONNECTION", "")

GRAPH_SERVICE_URL: str = os.getenv("GRAPH_SERVICE_URL", "http://localhost:8005")

# Publisher settings
PUBLISHER_BATCH_SIZE: int = int(os.getenv("PUBLISHER_BATCH_SIZE", "100"))
PUBLISHER_INTERVAL_SEC: float = float(os.getenv("PUBLISHER_INTERVAL_SEC", "5"))

# Transport mode: "local" (direct invocation) or "servicebus"
TRANSPORT_MODE: str = os.getenv("TRANSPORT_MODE", "local")
