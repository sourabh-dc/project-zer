"""
policy_engine.config
--------------------
Configuration for the OPA policy sidecar.
"""
import os
from dotenv import load_dotenv

load_dotenv()

POLICY_MODE: str = os.getenv("POLICY_MODE", "local")

OPA_URL: str = os.getenv("OPA_URL", "http://localhost:8181")

POLICY_LOG_DECISIONS: bool = os.getenv("POLICY_LOG_DECISIONS", "true").lower() == "true"
