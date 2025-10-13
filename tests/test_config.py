"""
Production Test Configuration
Centralized configuration for all test suites
"""

import os
from typing import Dict, Any

# Service configurations with correct ports
SERVICES = {
    "provisioning": {"port": 8212, "base_path": "/provisioning/v2"},
    "catalog": {"port": 8215, "base_path": "/catalog/v2"},
    "entry": {"port": 8218, "base_path": "/entry/v4"},
    "orders": {"port": 8224, "base_path": "/orders/v2"},
    "identity": {"port": 8219, "base_path": "/identity/v4"},
    "pricing": {"port": 8226, "base_path": "/pricing/v2"},
    "payments": {"port": 8225, "base_path": "/payments/v2"},
    "billing": {"port": 8214, "base_path": "/billing/v2"},
    "ledger": {"port": 8220, "base_path": "/ledger/v4"},
    "events": {"port": 8211, "base_path": "/events/v4"},
    "notifications": {"port": 8222, "base_path": "/notifications/v4"},
    "monitoring": {"port": 8221, "base_path": "/monitoring/v4"},
    "observability": {"port": 8223, "base_path": "/observability/v4"},
    "reports": {"port": 8227, "base_path": "/reports/v4"},
    "approvals": {"port": 8213, "base_path": "/approvals/v4"},
    "cv_connector": {"port": 8216, "base_path": "/cv/v4"},
    "cv_gateway": {"port": 8217, "base_path": "/cv/v4"},
    "usage": {"port": 8210, "base_path": "/usage/v4"},
    "entitlements": {"port": 8209, "base_path": "/entitlements/v4"},
    "subscriptions": {"port": 8208, "base_path": "/subscriptions/v4"},
    "service_registry": {"port": 8207, "base_path": "/registry/v4"}
}

# Test configuration
TEST_CONFIG = {
    "timeout": 30,
    "retry_count": 3,
    "retry_delay": 1,
    "test_tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "test_user_id": "550e8400-e29b-41d4-a716-446655440001",
    "test_site_id": "550e8400-e29b-41d4-a716-446655440002",
    "test_store_id": "550e8400-e29b-41d4-a716-446655440003"
}

def get_service_url(service_name: str) -> str:
    """Get service URL with correct port"""
    if service_name not in SERVICES:
        raise ValueError(f"Unknown service: {service_name}")
    
    service = SERVICES[service_name]
    return f"http://localhost:{service['port']}"

def get_service_base_path(service_name: str) -> str:
    """Get service base path"""
    if service_name not in SERVICES:
        raise ValueError(f"Unknown service: {service_name}")
    
    return SERVICES[service_name]["base_path"]
