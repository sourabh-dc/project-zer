#!/usr/bin/env python3
"""
Production Integration Tests
End-to-end integration tests for critical service flows
"""

import requests
import json
import time
import sys
import uuid
from test_config import SERVICES, TEST_CONFIG

def test_provisioning_flow():
    """Test provisioning service flow"""
    print("🏗️  Testing Provisioning Flow")
    print("-" * 30)
    
    try:
        # Test tenant creation
        tenant_data = {
            "tenant_name": f"test_tenant_{uuid.uuid4().hex[:8]}",
            "tenant_type": "enterprise",
            "contact_email": "test@example.com"
        }
        
        response = requests.post(
            f"{SERVICES['provisioning']['port']}/provisioning/v2/tenants",
            json=tenant_data,
            timeout=TEST_CONFIG["timeout"]
        )
        
        if response.status_code == 201:
            tenant = response.json()
            print(f"✅ Tenant created: {tenant['tenant_id']}")
            return True
        else:
            print(f"❌ Tenant creation failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Provisioning flow failed: {str(e)}")
        return False

def test_entry_flow():
    """Test entry service flow"""
    print("🚪 Testing Entry Flow")
    print("-" * 30)
    
    try:
        # Test entry code generation
        entry_data = {
            "tenant_id": TEST_CONFIG["test_tenant_id"],
            "user_id": TEST_CONFIG["test_user_id"],
            "expires_in_minutes": 60
        }
        
        response = requests.post(
            f"http://localhost:{SERVICES['entry']['port']}/entry/v4/codes",
            json=entry_data,
            timeout=TEST_CONFIG["timeout"]
        )
        
        if response.status_code == 201:
            entry = response.json()
            print(f"✅ Entry code generated: {entry['code']}")
            return True
        else:
            print(f"❌ Entry code generation failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Entry flow failed: {str(e)}")
        return False

def test_all_integration_flows():
    """Test all integration flows"""
    print("🔄 Testing Integration Flows")
    print("=" * 50)
    
    flows = [
        ("Provisioning", test_provisioning_flow),
        ("Entry", test_entry_flow)
    ]
    
    success_count = 0
    total_count = len(flows)
    
    for flow_name, flow_test in flows:
        print(f"\n{flow_name} Flow:")
        if flow_test():
            success_count += 1
        time.sleep(1)  # Delay between flows
    
    print("\n" + "=" * 50)
    print(f"Integration Summary: {success_count}/{total_count} flows successful")
    
    if success_count == total_count:
        print("🎉 All integration flows are working!")
        return True
    else:
        print("⚠️  Some integration flows failed")
        return False

if __name__ == "__main__":
    success = test_all_integration_flows()
    sys.exit(0 if success else 1)
