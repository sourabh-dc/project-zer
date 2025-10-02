#!/usr/bin/env python3
"""
Test script for ZeroQue V2 Streamlit app
Tests the core functionality of the V2 services
"""

import requests
import json
import uuid

# Service URLs
PROVISIONING_BASE = "http://localhost:8201"
ORDERS_BASE = "http://localhost:8203" 
PRICING_BASE = "http://localhost:8209"

def test_service_health():
    """Test health endpoints of all services"""
    print("🏥 Testing Service Health...")
    
    services = {
        "Provisioning": f"{PROVISIONING_BASE}/health",
        "Orders": f"{ORDERS_BASE}/health",
        "Pricing": f"{PRICING_BASE}/health"
    }
    
    for service_name, health_url in services.items():
        try:
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                print(f"✅ {service_name}: Healthy")
            else:
                print(f"⚠️ {service_name}: Status {response.status_code}")
        except Exception as e:
            print(f"❌ {service_name}: {str(e)}")
    print()

def test_provisioning_service():
    """Test provisioning service endpoints"""
    print("🏢 Testing Provisioning Service...")
    
    # Test tenant creation
    tenant_data = {
        "name": "Test Marketplace",
        "type": "marketplace", 
        "active": True
    }
    
    try:
        response = requests.post(f"{PROVISIONING_BASE}/provisioning/v2/tenants", 
                               json=tenant_data, timeout=10)
        if response.status_code in [200, 201]:
            print("✅ Tenant creation: Success")
            tenant_id = response.json().get("tenant_id")
            print(f"   Created tenant ID: {tenant_id}")
        else:
            print(f"⚠️ Tenant creation: Status {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Tenant creation: {str(e)}")
    
    # Test tenant listing
    try:
        response = requests.get(f"{PROVISIONING_BASE}/provisioning/v2/tenants", timeout=10)
        if response.status_code == 200:
            tenants = response.json()
            print(f"✅ Tenant listing: Found {len(tenants)} tenants")
        else:
            print(f"⚠️ Tenant listing: Status {response.status_code}")
    except Exception as e:
        print(f"❌ Tenant listing: {str(e)}")
    
    print()

def test_pricing_service():
    """Test pricing service endpoints"""
    print("💰 Testing Pricing Service...")
    
    # Test pricebook creation
    pricebook_data = {
        "name": "Test Pricebook",
        "description": "Test pricebook for demo",
        "pricebook_type": "standard",
        "currency": "GBP",
        "hierarchy_rank": 1,
        "active": True
    }
    
    try:
        response = requests.post(f"{PRICING_BASE}/pricing/v2/pricebooks", 
                               json=pricebook_data, timeout=10)
        if response.status_code in [200, 201]:
            print("✅ Pricebook creation: Success")
            pricebook_id = response.json().get("pricebook_id")
            print(f"   Created pricebook ID: {pricebook_id}")
        else:
            print(f"⚠️ Pricebook creation: Status {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Pricebook creation: {str(e)}")
    
    # Test pricebook listing
    try:
        response = requests.get(f"{PRICING_BASE}/pricing/v2/pricebooks", timeout=10)
        if response.status_code == 200:
            pricebooks = response.json()
            print(f"✅ Pricebook listing: Found {len(pricebooks)} pricebooks")
        else:
            print(f"⚠️ Pricebook listing: Status {response.status_code}")
    except Exception as e:
        print(f"❌ Pricebook listing: {str(e)}")
    
    print()

def test_orders_service():
    """Test orders service endpoints"""
    print("🛒 Testing Orders Service...")
    
    # Test order listing (should work even without creating orders)
    try:
        response = requests.get(f"{ORDERS_BASE}/orders/v2", timeout=10)
        if response.status_code == 200:
            orders = response.json()
            print(f"✅ Order listing: Found {len(orders)} orders")
        else:
            print(f"⚠️ Order listing: Status {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ Order listing: {str(e)}")
    
    print()

def main():
    """Run all tests"""
    print("🚀 ZeroQue V2 Streamlit App Test Suite")
    print("=" * 50)
    
    test_service_health()
    test_provisioning_service()
    test_pricing_service()
    test_orders_service()
    
    print("🎉 Test suite completed!")
    print("\n📱 Access the Streamlit V2 app at: http://localhost:8501")

if __name__ == "__main__":
    main()
