#!/usr/bin/env python3
"""
Test script to check the current status of all services
"""

import requests
import json
from datetime import datetime

# Service configurations
SERVICES = {
    "events": {"port": 8087, "health_path": "/events/v4/health"},
    "entry": {"port": 8084, "health_path": "/entry/v4/health"},
    "identity": {"port": 8085, "health_path": "/identity/v4/health"},
    "pricing": {"port": 8086, "health_path": "/pricing/v2/health"},
    "orders": {"port": 8080, "health_path": "/orders/v2/health"},
    "provisioning": {"port": 8081, "health_path": "/provisioning/v2/health"},
    "catalog": {"port": 8082, "health_path": "/catalog/v2/health"},
    "approvals": {"port": 8083, "health_path": "/approvals/v2/health"},
    "billing": {"port": 8083, "health_path": "/billing/v2/health"},
}

def test_service_health(service_name, config):
    """Test if a service is healthy"""
    try:
        response = requests.get(f"http://localhost:{config['port']}{config['health_path']}", timeout=3)
        if response.status_code == 200:
            return "✅ HEALTHY", response.json()
        else:
            return f"❌ UNHEALTHY ({response.status_code})", None
    except requests.exceptions.ConnectionError:
        return "❌ NOT RUNNING", None
    except requests.exceptions.Timeout:
        return "⏱️ TIMEOUT", None
    except Exception as e:
        return f"❌ ERROR: {str(e)}", None

def main():
    """Test all services"""
    print("🚀 Zeroque Services Status Check")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    healthy_count = 0
    total_count = len(SERVICES)
    
    for service_name, config in SERVICES.items():
        status, data = test_service_health(service_name, config)
        print(f"{service_name.upper():<15} {status}")
        
        if "HEALTHY" in status:
            healthy_count += 1
            if data:
                print(f"{'':15} Version: {data.get('version', 'unknown')}")
                print(f"{'':15} Service: {data.get('service', 'unknown')}")
    
    print()
    print("=" * 60)
    print(f"📊 SUMMARY: {healthy_count}/{total_count} services healthy")
    
    if healthy_count == total_count:
        print("🎉 All services are running and healthy!")
        return True
    elif healthy_count > 0:
        print(f"⚠️  {healthy_count} services are running, {total_count - healthy_count} need attention")
        return False
    else:
        print("❌ No services are currently running")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
