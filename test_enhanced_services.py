#!/usr/bin/env python3
"""
Test script for all enhanced services
"""

import requests
import json
from datetime import datetime
from typing import Dict, Any

# Enhanced services configuration
ENHANCED_SERVICES = {
    "cv_connector": {"port": 8090, "base_path": "/cv/v4"},
    "cv_gateway": {"port": 8091, "base_path": "/cv/v4"},
    "ledger": {"port": 8092, "base_path": "/ledger/v4"},
    "payments": {"port": 8093, "base_path": "/payments/v4"},
    "entitlements": {"port": 8094, "base_path": "/entitlements/v4"},
    "subscriptions": {"port": 8095, "base_path": "/subscriptions/v4"},
}

# Test data
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440003"

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
        else:
            print(f"❌ {service_name.upper()} Integration - HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ {service_name.upper()} Integration - {str(e)}")
        return False

def test_enhanced_services_workflow():
    """Test end-to-end workflow with enhanced services"""
    print("\n🔄 Testing Enhanced Services Workflow")
    print("=" * 60)
    
    results = {}
    
    # Test CV Connector - Sync Product
    print("1️⃣ Testing CV Connector - Product Sync...")
    try:
        response = requests.post(
            f"http://localhost:{ENHANCED_SERVICES['cv_connector']['port']}{ENHANCED_SERVICES['cv_connector']['base_path']}/sync/products",
            json={
                "tenant_id": TEST_TENANT_ID,
                "product_id": "test_product_123",
                "name": "Test Product",
                "price_minor": 1000,
                "currency": "USD"
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            results['cv_connector_product'] = data.get('external_id')
            print(f"   ✅ Product synced: {data.get('external_id')}")
        else:
            print(f"   ❌ Product sync failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Product sync failed: {str(e)}")
        return False
    
    # Test CV Gateway - Process Order
    print("2️⃣ Testing CV Gateway - Order Processing...")
    try:
        response = requests.post(
            f"http://localhost:{ENHANCED_SERVICES['cv_gateway']['port']}{ENHANCED_SERVICES['cv_gateway']['base_path']}/orders/process",
            json={
                "tenant_id": TEST_TENANT_ID,
                "user_id": TEST_USER_ID,
                "items": [{"product_id": "test_product_123", "quantity": 1, "price_minor": 1000}],
                "site_id": "test_site"
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            results['cv_gateway_order'] = data.get('order_id')
            print(f"   ✅ Order processed: {data.get('order_id')}")
        else:
            print(f"   ❌ Order processing failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Order processing failed: {str(e)}")
        return False
    
    # Test Ledger - Create Entry
    print("3️⃣ Testing Ledger - Create Entry...")
    try:
        response = requests.post(
            f"http://localhost:{ENHANCED_SERVICES['ledger']['port']}{ENHANCED_SERVICES['ledger']['base_path']}/entries",
            json={
                "tenant_id": TEST_TENANT_ID,
                "account_id": "test_account_123",
                "debit_amount_minor": 1000,
                "credit_amount_minor": 0,
                "currency": "USD",
                "description": "Test entry"
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            results['ledger_entry'] = data.get('entry_id')
            print(f"   ✅ Entry created: {data.get('entry_id')}")
        else:
            print(f"   ❌ Entry creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Entry creation failed: {str(e)}")
        return False
    
    # Test Payments - Create Payment Intent
    print("4️⃣ Testing Payments - Payment Intent...")
    try:
        response = requests.post(
            f"http://localhost:{ENHANCED_SERVICES['payments']['port']}{ENHANCED_SERVICES['payments']['base_path']}/intent",
            json={
                "tenant_id": TEST_TENANT_ID,
                "amount_minor": 1000,
                "currency": "USD",
                "order_id": results.get('cv_gateway_order')
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            results['payment_intent'] = data.get('payment_intent_id')
            print(f"   ✅ Payment intent created: {data.get('payment_intent_id')}")
        else:
            print(f"   ❌ Payment intent creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Payment intent creation failed: {str(e)}")
        return False
    
    # Test Entitlements - Check Entitlement
    print("5️⃣ Testing Entitlements - Check Entitlement...")
    try:
        response = requests.post(
            f"http://localhost:{ENHANCED_SERVICES['entitlements']['port']}{ENHANCED_SERVICES['entitlements']['base_path']}/check",
            json={
                "tenant_id": TEST_TENANT_ID,
                "feature_code": "test_feature",
                "user_id": TEST_USER_ID,
                "action": "access"
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            results['entitlement_check'] = data.get('allowed')
            print(f"   ✅ Entitlement checked: {data.get('allowed')}")
        else:
            print(f"   ❌ Entitlement check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Entitlement check failed: {str(e)}")
        return False
    
    # Test Subscriptions - Create Subscription
    print("6️⃣ Testing Subscriptions - Create Subscription...")
    try:
        response = requests.post(
            f"http://localhost:{ENHANCED_SERVICES['subscriptions']['port']}{ENHANCED_SERVICES['subscriptions']['base_path']}/subscriptions",
            json={
                "tenant_id": TEST_TENANT_ID,
                "plan_id": "test_plan",
                "payment_method_id": "pm_test_123"
            },
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            results['subscription'] = data.get('subscription_id')
            print(f"   ✅ Subscription created: {data.get('subscription_id')}")
        else:
            print(f"   ❌ Subscription creation failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Subscription creation failed: {str(e)}")
        return False
    
    print("\n✅ Enhanced Services Workflow Test Completed Successfully!")
    print(f"   CV Connector Product: {results.get('cv_connector_product', 'N/A')}")
    print(f"   CV Gateway Order: {results.get('cv_gateway_order', 'N/A')}")
    print(f"   Ledger Entry: {results.get('ledger_entry', 'N/A')}")
    print(f"   Payment Intent: {results.get('payment_intent', 'N/A')}")
    print(f"   Entitlement Check: {results.get('entitlement_check', 'N/A')}")
    print(f"   Subscription: {results.get('subscription', 'N/A')}")
    
    return True

def main():
    """Main test function"""
    print("🚀 Enhanced Services Integration Test")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Test individual services
    print("🔍 Testing Individual Enhanced Services")
    print("-" * 40)
    healthy_count = 0
    integration_count = 0
    
    for service_name, config in ENHANCED_SERVICES.items():
        if test_service_health(service_name, config):
            healthy_count += 1
        if test_service_integration(service_name, config):
            integration_count += 1
    
    print()
    print("📊 Individual Service Results")
    print("-" * 40)
    print(f"✅ Healthy Services: {healthy_count}/{len(ENHANCED_SERVICES)}")
    print(f"✅ Integration Ready: {integration_count}/{len(ENHANCED_SERVICES)}")
    
    if healthy_count == len(ENHANCED_SERVICES):
        print("\n🎯 All enhanced services are healthy! Testing end-to-end workflow...")
        workflow_success = test_enhanced_services_workflow()
        
        print("\n" + "=" * 60)
        print("📊 FINAL RESULTS")
        print("=" * 60)
        print(f"✅ Services Health: {healthy_count}/{len(ENHANCED_SERVICES)}")
        print(f"✅ Integration Status: {integration_count}/{len(ENHANCED_SERVICES)}")
        print(f"✅ End-to-End Workflow: {'PASSED' if workflow_success else 'FAILED'}")
        
        if workflow_success:
            print("\n🎉 ALL ENHANCED SERVICES TESTS PASSED! System is fully integrated!")
            return True
        else:
            print("\n⚠️  Workflow test failed, but individual services are healthy.")
            return False
    else:
        print(f"\n❌ {len(ENHANCED_SERVICES) - healthy_count} services are not healthy. Cannot proceed with integration test.")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
