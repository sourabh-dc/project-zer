"""
Load Test Configuration
Configuration for Locust load testing
"""

import os

# Service endpoints for load testing
SERVICE_ENDPOINTS = {
    "provisioning": "http://localhost:8212",
    "catalog": "http://localhost:8215",
    "entry": "http://localhost:8218",
    "orders": "http://localhost:8224",
    "identity": "http://localhost:8219",
    "pricing": "http://localhost:8226",
    "payments": "http://localhost:8225",
    "billing": "http://localhost:8214",
    "ledger": "http://localhost:8220",
    "events": "http://localhost:8211",
    "notifications": "http://localhost:8222",
    "monitoring": "http://localhost:8221",
    "observability": "http://localhost:8223",
    "reports": "http://localhost:8227",
    "approvals": "http://localhost:8213",
    "cv_connector": "http://localhost:8216",
    "cv_gateway": "http://localhost:8217",
    "usage": "http://localhost:8210",
    "entitlements": "http://localhost:8209",
    "subscriptions": "http://localhost:8208",
    "service_registry": "http://localhost:8207"
}

# Load test parameters
LOAD_TEST_CONFIG = {
    "users": 10,
    "spawn_rate": 2,
    "run_time": "5m",
    "host": "http://localhost:8212"  # Default to provisioning service
}
