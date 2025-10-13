#!/usr/bin/env python3
"""
Production Health Check Tests
Comprehensive health checks for all services
"""

import requests
import time
import sys
from test_config import SERVICES, TEST_CONFIG

def test_service_health(service_name: str, service_config: dict) -> bool:
    """Test individual service health"""
    try:
        url = f"http://localhost:{service_config['port']}/health"
        response = requests.get(url, timeout=TEST_CONFIG["timeout"])
        
        if response.status_code == 200:
            print(f"✅ {service_name}: Healthy")
            return True
        else:
            print(f"❌ {service_name}: Unhealthy (Status: {response.status_code})")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ {service_name}: Unreachable ({str(e)})")
        return False

def test_all_services_health():
    """Test health of all services"""
    print("🏥 Testing Service Health Checks")
    print("=" * 50)
    
    healthy_count = 0
    total_count = len(SERVICES)
    
    for service_name, service_config in SERVICES.items():
        if test_service_health(service_name, service_config):
            healthy_count += 1
        time.sleep(0.5)  # Small delay between requests
    
    print("\n" + "=" * 50)
    print(f"Health Check Summary: {healthy_count}/{total_count} services healthy")
    
    if healthy_count == total_count:
        print("🎉 All services are healthy!")
        return True
    else:
        print("⚠️  Some services are unhealthy or unreachable")
        return False

if __name__ == "__main__":
    success = test_all_services_health()
    sys.exit(0 if success else 1)
