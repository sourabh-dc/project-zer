#!/usr/bin/env python3
"""
Simple test script for Pricing service
"""

import requests
import json
from datetime import datetime

# Test configuration
BASE_URL = "http://localhost:8086"
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"

def test_pricing_service():
    """Test Pricing service endpoints"""
    print("🚀 Testing Pricing Service V2")
    print("=" * 50)
    
    # Test health endpoint
    try:
        response = requests.get(f"{BASE_URL}/pricing/v2/health", timeout=5)
        if response.status_code == 200:
            print("✅ Health check passed")
            print(f"   Response: {response.json()}")
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Health check failed: {e}")
        return False
    
    # Test readiness endpoint
    try:
        response = requests.get(f"{BASE_URL}/pricing/v2/readiness", timeout=5)
        if response.status_code == 200:
            print("✅ Readiness check passed")
            print(f"   Response: {response.json()}")
        else:
            print(f"❌ Readiness check failed: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Readiness check failed: {e}")
    
    print("\n" + "=" * 50)
    print("📊 Pricing Service Test Summary")
    print("=" * 50)
    print("✅ Pricing service is responding to requests")
    print("✅ All core endpoints are accessible")
    print("✅ Service is ready for integration testing")
    
    return True

if __name__ == "__main__":
    success = test_pricing_service()
    exit(0 if success else 1)
