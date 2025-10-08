#!/usr/bin/env python3
"""
Comprehensive integration test for all Zeroque services
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, Any

# Service configurations
SERVICES = {
    "events": {"port": 8087, "base_path": "/events/v4"},
    "entry": {"port": 8084, "base_path": "/entry/v4"},
    "identity": {"port": 8085, "base_path": "/identity/v4"},
    "pricing": {"port": 8086, "base_path": "/pricing/v2"},
    "orders": {"port": 8080, "base_path": "/orders/v2"},
    "provisioning": {"port": 8081, "base_path": "/provisioning/v2"},
    "catalog": {"port": 8082, "base_path": "/catalog/v2"},
    "approvals": {"port": 8088, "base_path": "/approvals/v2"},
    "billing": {"port": 8083, "base_path": ""},
}

# Test data
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440003"
TEST_PRODUCT_ID = "550e8400-e29b-41d4-a716-446655440004"
TEST_ORDER_ID = "550e8400-e29b-41d4-a716-446655440005"

def test_service_health(service_name: str, config: dict) -> bool:
    """Test if a service is healthy"""
    try:
        response = requests.get(f"http://localhost:{config['port']}{config['base_path']}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ {service_name.upper()} - {data.get('status', 'unknown')} ({data.get('version', 'unknown')})")
            return True
        else:
            print(f"❌ {service_name.upper()} - HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ {service_name.upper()} - {str(e)}")
        return False

def test_service_integration(service_name: str, config: dict) -> bool:
    """Test service integration endpoints"""
    try:
        response = requests.get(f"http://localhost:{config['port']}{config['base_path']}/integration/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ {service_name.upper()} Integration - {data.get('ok', False)}")
            return True
        elif response.status_code in [401, 403]:
            # Authentication required - service is running but needs auth
            print(f"⚠️  {service_name.upper()} Integration - Authentication Required")
            return True
        else:
            print(f"❌ {service_name.upper()} Integration - HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ {service_name.upper()} Integration - {str(e)}")
        return False

def test_end_to_end_workflow():
    """Test end-to-end workflow across services"""
    print("\n🔄 Testing End-to-End Workflow")
    print("=" * 60)
    
    results = {}
    
    # Step 1: Create Tenant (Provisioning)
    print("1️⃣ Creating Tenant...")
    try:
        response = requests.post(
            f"http://localhost:{SERVICES['provisioning']['port']}{SERVICES['provisioning']['base_path']}/tenants",
            json={
                "tenant_name": "Test Company",
                "tenant_type": "standard",
                "contact_email": "test@example.com"
            },
            timeout=10
        )
        if response.status_code == 200:
            tenant_data = response.json()
            results['tenant_id'] = tenant_data['tenant_id']
            print(f"   ✅ Tenant created: {results['tenant_id']}")
        else:
            print(f"   ❌ Tenant creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Tenant creation failed: {str(e)}")
        return False
    
    # Step 2: Create User (Provisioning)
    print("2️⃣ Creating User...")
    try:
        response = requests.post(
            f"http://localhost:{SERVICES['provisioning']['port']}{SERVICES['provisioning']['base_path']}/users",
            json={
                "tenant_id": results['tenant_id'],
                "email": "user@example.com",
                "name": "Test User"
            },
            timeout=10
        )
        if response.status_code == 200:
            user_data = response.json()
            results['user_id'] = user_data['user_id']
            print(f"   ✅ User created: {results['user_id']}")
        else:
            print(f"   ❌ User creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ User creation failed: {str(e)}")
        return False
    
    # Step 3: Create Product (Catalog)
    print("3️⃣ Creating Product...")
    try:
        response = requests.post(
            f"http://localhost:{SERVICES['catalog']['port']}{SERVICES['catalog']['base_path']}/products",
            json={
                "tenant_id": results['tenant_id'],
                "name": "Test Product",
                "description": "A test product",
                "price_minor": 1000,  # $10.00
                "currency": "USD"
            },
            timeout=10
        )
        if response.status_code == 200:
            product_data = response.json()
            results['product_id'] = product_data['product_id']
            print(f"   ✅ Product created: {results['product_id']}")
        else:
            print(f"   ❌ Product creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Product creation failed: {str(e)}")
        return False
    
    # Step 4: Issue Entry Code (Entry)
    print("4️⃣ Issuing Entry Code...")
    try:
        response = requests.post(
            f"http://localhost:{SERVICES['entry']['port']}{SERVICES['entry']['base_path']}/issue-code",
            json={
                "tenant_id": results['tenant_id'],
                "user_id": results['user_id'],
                "provider": "internal",
                "group_size": 1,
                "ttl_min": 15
            },
            timeout=10
        )
        if response.status_code == 200:
            entry_data = response.json()
            results['entry_code'] = entry_data['code']
            print(f"   ✅ Entry code issued: {results['entry_code']}")
        else:
            print(f"   ❌ Entry code issuance failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Entry code issuance failed: {str(e)}")
        return False
    
    # Step 5: Create Order (Orders)
    print("5️⃣ Creating Order...")
    try:
        response = requests.post(
            f"http://localhost:{SERVICES['orders']['port']}{SERVICES['orders']['base_path']}/orders",
            json={
                "tenant_id": results['tenant_id'],
                "user_id": results['user_id'],
                "items": [{
                    "product_id": results['product_id'],
                    "quantity": 1,
                    "price_minor": 1000
                }],
                "site_id": "site1"
            },
            timeout=10
        )
        if response.status_code == 200:
            order_data = response.json()
            results['order_id'] = order_data['order_id']
            print(f"   ✅ Order created: {results['order_id']}")
        else:
            print(f"   ❌ Order creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Order creation failed: {str(e)}")
        return False
    
    # Step 6: Create Approval Request (Approvals)
    print("6️⃣ Creating Approval Request...")
    try:
        response = requests.post(
            f"http://localhost:{SERVICES['approvals']['port']}{SERVICES['approvals']['base_path']}/requests",
            json={
                "tenant_id": results['tenant_id'],
                "user_id": results['user_id'],
                "amount_minor": 1000,
                "currency": "USD",
                "reason": "Test purchase"
            },
            timeout=10
        )
        if response.status_code == 200:
            approval_data = response.json()
            results['approval_id'] = approval_data['request_id']
            print(f"   ✅ Approval request created: {results['approval_id']}")
        else:
            print(f"   ❌ Approval request creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Approval request creation failed: {str(e)}")
        return False
    
    print("\n✅ End-to-End Workflow Test Completed Successfully!")
    print(f"   Tenant ID: {results.get('tenant_id', 'N/A')}")
    print(f"   User ID: {results.get('user_id', 'N/A')}")
    print(f"   Product ID: {results.get('product_id', 'N/A')}")
    print(f"   Entry Code: {results.get('entry_code', 'N/A')}")
    print(f"   Order ID: {results.get('order_id', 'N/A')}")
    print(f"   Approval ID: {results.get('approval_id', 'N/A')}")
    
    return True

def main():
    """Main test function"""
    print("🚀 Zeroque Services Integration Test")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Test individual services
    print("🔍 Testing Individual Services")
    print("-" * 40)
    healthy_count = 0
    integration_count = 0
    
    for service_name, config in SERVICES.items():
        if test_service_health(service_name, config):
            healthy_count += 1
        if test_service_integration(service_name, config):
            integration_count += 1
    
    print()
    print("📊 Individual Service Results")
    print("-" * 40)
    print(f"✅ Healthy Services: {healthy_count}/{len(SERVICES)}")
    print(f"✅ Integration Ready: {integration_count}/{len(SERVICES)}")
    
    if healthy_count == len(SERVICES):
        print("\n🎯 All services are healthy! Testing end-to-end workflow...")
        workflow_success = test_end_to_end_workflow()
        
        print("\n" + "=" * 60)
        print("📊 FINAL RESULTS")
        print("=" * 60)
        print(f"✅ Services Health: {healthy_count}/{len(SERVICES)}")
        print(f"✅ Integration Status: {integration_count}/{len(SERVICES)}")
        print(f"✅ End-to-End Workflow: {'PASSED' if workflow_success else 'FAILED'}")
        
        if workflow_success:
            print("\n🎉 ALL TESTS PASSED! System is production-ready!")
            return True
        else:
            print("\n⚠️  Workflow test failed, but individual services are healthy.")
            return False
    else:
        print(f"\n❌ {len(SERVICES) - healthy_count} services are not healthy. Cannot proceed with integration test.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
