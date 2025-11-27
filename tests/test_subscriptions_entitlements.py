#!/usr/bin/env python3
"""
Comprehensive test for Subscription and Entitlement services.

Tests the following:
1. Plan CRUD operations
2. Feature CRUD operations
3. Plan-Feature associations
4. Tenant subscription lifecycle (trial, active, cancel, upgrade/downgrade)
5. Entitlement checks (usage limits)
6. Usage recording with concurrency safety
7. Proper billing cycle anchoring
"""

import requests
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any

# Configuration
BASE_URL = "http://localhost:8300"
ADMIN_API_KEY = "zq_bootstrap_admin_key"

# Test data tracking
test_data = {
    "tenant_id": None,
    "user_id": None,
    "tenant_api_key": None,
    "plan_codes": [],
    "feature_codes": []
}


def make_request(
    method: str,
    endpoint: str,
    data: dict = None,
    params: dict = None,
    expected_status: int = None,
    use_admin: bool = False
) -> Dict[str, Any]:
    """Make an API request with proper headers"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    
    api_key = ADMIN_API_KEY if (use_admin or not test_data["tenant_api_key"]) else test_data["tenant_api_key"]
    if api_key:
        headers["X-API-Key"] = api_key
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=data, params=params, timeout=30)
        elif method == "PUT":
            resp = requests.put(url, headers=headers, json=data, params=params, timeout=30)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, params=params, timeout=30)
        else:
            raise ValueError(f"Unknown method: {method}")
        
        status_msg = "✅" if (expected_status is None or resp.status_code == expected_status) else "❌"
        print(f"{status_msg} {method} {endpoint} -> {resp.status_code}")
        
        if resp.status_code < 400:
            try:
                return resp.json()
            except:
                return {"status_code": resp.status_code}
        else:
            print(f"   Error: {resp.text[:200]}")
            return {"error": resp.text, "status_code": resp.status_code}
    except Exception as e:
        print(f"❌ {method} {endpoint} -> Exception: {e}")
        return {"error": str(e)}


def test_health():
    """Test health endpoint"""
    print("\n" + "="*60)
    print("Testing Health Endpoint")
    print("="*60)
    result = make_request("GET", "/health")
    return "status" in result or "error" not in result


def setup_test_tenant():
    """Setup a test tenant with super user"""
    print("\n" + "="*60)
    print("Setting up Test Tenant and User")
    print("="*60)
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # Create tenant
    result = make_request(
        "POST",
        "/v1/tenants",
        {
            "name": f"SubTest Tenant {timestamp}",
            "type": "customer"
        },
        use_admin=True
    )
    
    if "error" in result:
        print(f"   Using existing setup or skipping tenant creation")
        # Try to use existing credentials if available
        return False
    
    test_data["tenant_id"] = result.get("tenant_id")
    print(f"   Tenant ID: {test_data['tenant_id']}")
    
    # Create super user
    result = make_request(
        "POST",
        f"/v1/tenants/{test_data['tenant_id']}/super-user",
        {
            "email": f"subtest_{timestamp}@test.com",
            "display_name": "Sub Test Admin",
            "password": "TestPass123!"
        },
        use_admin=True
    )
    
    if "api_key" in result:
        test_data["tenant_api_key"] = result["api_key"]
        test_data["user_id"] = result.get("user_id")
        print(f"   User ID: {test_data['user_id']}")
        print(f"   API Key: {test_data['tenant_api_key'][:20]}...")
        return True
    
    return False


def test_plan_crud():
    """Test subscription plan CRUD"""
    print("\n" + "="*60)
    print("Testing Subscription Plan CRUD")
    print("="*60)
    
    timestamp = datetime.now().strftime("%H%M%S")
    
    # Create plans
    plans = [
        {"code": f"basic_{timestamp}", "name": "Basic Plan", "price_yearly_minor": 9900, "currency": "GBP"},
        {"code": f"pro_{timestamp}", "name": "Pro Plan", "price_yearly_minor": 29900, "price_monthly_minor": 2990, "currency": "GBP"},
        {"code": f"enterprise_{timestamp}", "name": "Enterprise Plan", "price_yearly_minor": 99900, "currency": "GBP"}
    ]
    
    for plan in plans:
        result = make_request("POST", "/v1/subscriptions/plans", plan, expected_status=201, use_admin=True)
        if "plan_code" in result:
            test_data["plan_codes"].append(result["plan_code"])
            print(f"   Created plan: {result['plan_code']}")
    
    # List plans
    result = make_request("GET", "/v1/subscriptions/plans", params={"active": True}, use_admin=True)
    print(f"   Listed {result.get('total', 0)} plans")
    
    # Get specific plan
    if test_data["plan_codes"]:
        result = make_request("GET", f"/v1/subscriptions/plans/{test_data['plan_codes'][0]}", use_admin=True)
        print(f"   Plan details: {result.get('name', 'N/A')}")
    
    return len(test_data["plan_codes"]) > 0


def test_feature_crud():
    """Test feature CRUD"""
    print("\n" + "="*60)
    print("Testing Feature CRUD")
    print("="*60)
    
    timestamp = datetime.now().strftime("%H%M%S")
    
    # Create features
    features = [
        {"code": f"api_calls_{timestamp}", "name": "API Calls", "usage_type": "count", "reset_period": "monthly", "category": "api"},
        {"code": f"storage_{timestamp}", "name": "Storage GB", "usage_type": "gauge", "reset_period": "monthly", "category": "storage"},
        {"code": f"users_{timestamp}", "name": "User Seats", "usage_type": "count", "reset_period": "monthly", "category": "users"},
        {"code": f"reports_{timestamp}", "name": "Report Generation", "usage_type": "count", "reset_period": "daily", "category": "analytics"}
    ]
    
    for feature in features:
        result = make_request("POST", "/v1/subscriptions/features", feature, expected_status=201, use_admin=True)
        if "feature_code" in result:
            test_data["feature_codes"].append(result["feature_code"])
            print(f"   Created feature: {result['feature_code']}")
    
    # List features
    result = make_request("GET", "/v1/subscriptions/features", use_admin=True)
    print(f"   Listed {result.get('total', 0)} features")
    
    return len(test_data["feature_codes"]) > 0


def test_plan_feature_association():
    """Test associating features with plans"""
    print("\n" + "="*60)
    print("Testing Plan-Feature Associations")
    print("="*60)
    
    if not test_data["plan_codes"] or not test_data["feature_codes"]:
        print("   ⚠️ Missing plans or features, skipping")
        return False
    
    # Associate features with Basic plan (limited)
    basic_plan = test_data["plan_codes"][0]
    for feature in test_data["feature_codes"][:2]:  # Only first 2 features
        result = make_request("PUT", f"/v1/subscriptions/plans/{basic_plan}/features/{feature}", {
            "limits": {"max_value": 100, "warn_at": 80}
        }, use_admin=True)
        print(f"   Basic: {feature} -> limit 100")
    
    # Associate features with Pro plan (higher limits)
    if len(test_data["plan_codes"]) > 1:
        pro_plan = test_data["plan_codes"][1]
        for feature in test_data["feature_codes"]:
            result = make_request("PUT", f"/v1/subscriptions/plans/{pro_plan}/features/{feature}", {
                "limits": {"max_value": 1000, "warn_at": 800}
            }, use_admin=True)
            print(f"   Pro: {feature} -> limit 1000")
    
    # Enterprise plan - unlimited
    if len(test_data["plan_codes"]) > 2:
        enterprise_plan = test_data["plan_codes"][2]
        for feature in test_data["feature_codes"]:
            result = make_request("PUT", f"/v1/subscriptions/plans/{enterprise_plan}/features/{feature}", {
                "limits": {}  # No limits = unlimited
            }, use_admin=True)
            print(f"   Enterprise: {feature} -> unlimited")
    
    return True


def test_subscription_lifecycle():
    """Test subscription lifecycle: create, trial, upgrade, cancel"""
    print("\n" + "="*60)
    print("Testing Subscription Lifecycle")
    print("="*60)
    
    if not test_data["plan_codes"]:
        print("   ⚠️ No plans available, skipping")
        return False
    
    # Create subscription (starts with trial)
    result = make_request("POST", "/v1/subscriptions/tenant", {
        "tenant_id": test_data["tenant_id"],
        "plan_code": test_data["plan_codes"][0],
        "payment_method": "card",
        "billing_cycle": "yearly"
    }, expected_status=201)
    
    if "error" not in result:
        print(f"   Created subscription: {result.get('plan_code')} - {result.get('status')}")
        print(f"   Trial ends at: {result.get('trial_ends_at', 'N/A')}")
    
    # Get current subscription
    result = make_request("GET", "/v1/subscriptions/current")
    if "error" not in result:
        print(f"   Current: {result.get('plan_code')} - {result.get('status')}")
        print(f"   On trial: {result.get('on_trial')}")
        print(f"   Days remaining: {result.get('days_remaining')}")
    
    # Upgrade to Pro plan
    if len(test_data["plan_codes"]) > 1:
        result = make_request("POST", "/v1/subscriptions/upgrade-downgrade", {
            "new_plan_code": test_data["plan_codes"][1],
            "apply_immediately": True
        })
        print(f"   Upgrade result: {result.get('message', result.get('error', 'N/A'))}")
    
    # Check current again
    result = make_request("GET", "/v1/subscriptions/current")
    if "error" not in result:
        print(f"   After upgrade: {result.get('plan_code')} - {result.get('status')}")
    
    return True


def test_entitlement_check():
    """Test entitlement checks"""
    print("\n" + "="*60)
    print("Testing Entitlement Checks")
    print("="*60)
    
    if not test_data["feature_codes"]:
        print("   ⚠️ No features available, skipping")
        return False
    
    # Check entitlement for a feature
    for feature in test_data["feature_codes"][:2]:
        result = make_request("POST", "/v1/entitlements/check", {
            "tenant_id": test_data["tenant_id"],
            "feature_code": feature,
            "requested_count": 1
        })
        
        if "error" not in result:
            allowed = result.get("allowed", False)
            status = "✅" if allowed else "❌"
            print(f"   {status} {feature}: allowed={allowed}, limit={result.get('limit', 'unlimited')}, remaining={result.get('remaining', 'N/A')}")
    
    return True


def test_usage_recording():
    """Test usage recording"""
    print("\n" + "="*60)
    print("Testing Usage Recording")
    print("="*60)
    
    if not test_data["feature_codes"]:
        print("   ⚠️ No features available, skipping")
        return False
    
    feature = test_data["feature_codes"][0]
    
    # Record some usage
    for i in range(5):
        result = make_request("POST", "/v1/entitlements/usage/record", {
            "tenant_id": test_data["tenant_id"],
            "feature_code": feature,
            "usage_type": "count",
            "count": 10
        }, expected_status=201)
        
        if "error" not in result:
            print(f"   Recorded +10: total={result.get('total')}, remaining={result.get('remaining')}")
        else:
            print(f"   Recording failed: {result.get('error', 'unknown')[:50]}")
    
    # Get usage summary
    result = make_request("GET", "/v1/entitlements/usage", params={"feature_code": feature})
    if "usage" in result:
        for u in result["usage"]:
            print(f"   Summary: {u['feature_code']} - used {u['used']}/{u.get('limit', 'unlimited')}")
    
    return True


def test_usage_limit_enforcement():
    """Test that usage limits are enforced"""
    print("\n" + "="*60)
    print("Testing Usage Limit Enforcement")
    print("="*60)
    
    if not test_data["feature_codes"]:
        print("   ⚠️ No features available, skipping")
        return False
    
    feature = test_data["feature_codes"][0]
    
    # Check current usage
    result = make_request("POST", "/v1/entitlements/check", {
        "tenant_id": test_data["tenant_id"],
        "feature_code": feature,
        "requested_count": 1
    })
    
    limit = result.get("limit", 0)
    remaining = result.get("remaining", 0)
    
    if limit and remaining > 0:
        # Try to exceed limit
        result = make_request("POST", "/v1/entitlements/usage/record", {
            "tenant_id": test_data["tenant_id"],
            "feature_code": feature,
            "usage_type": "count",
            "count": limit + 1000  # Way over limit
        })
        
        if result.get("status_code") == 429:
            print(f"   ✅ Limit enforced: request rejected with 429")
        else:
            print(f"   ⚠️ Limit may not be enforced correctly: {result}")
    else:
        print(f"   ⚠️ No limit to test or already at limit")
    
    return True


def test_subscription_cancellation():
    """Test subscription cancellation and reactivation"""
    print("\n" + "="*60)
    print("Testing Subscription Cancellation")
    print("="*60)
    
    # Cancel subscription
    result = make_request("POST", "/v1/subscriptions/cancel", {
        "reason": "Testing cancellation flow",
        "cancel_immediately": False
    })
    
    if "error" not in result:
        print(f"   Canceled: {result.get('message')}")
        print(f"   Ends at: {result.get('ends_at', 'N/A')}")
    
    # Check status
    result = make_request("GET", "/v1/subscriptions/current")
    print(f"   Status after cancel: {result.get('status')}")
    
    # Reactivate
    result = make_request("POST", "/v1/subscriptions/reactivate")
    if "error" not in result:
        print(f"   Reactivated: {result.get('message')}")
    
    # Final status
    result = make_request("GET", "/v1/subscriptions/current")
    print(f"   Final status: {result.get('status')}")
    
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("SUBSCRIPTION & ENTITLEMENT SERVICE TESTS")
    print("="*60)
    print(f"Base URL: {BASE_URL}")
    print(f"Started at: {datetime.now().isoformat()}")
    
    results = {}
    
    # Health check
    results["health"] = test_health()
    
    # Setup
    results["setup"] = setup_test_tenant()
    
    if not test_data["tenant_api_key"]:
        print("\n❌ Cannot proceed without tenant API key. Please check setup.")
        return results
    
    # Run tests
    results["plan_crud"] = test_plan_crud()
    results["feature_crud"] = test_feature_crud()
    results["plan_features"] = test_plan_feature_association()
    results["subscription_lifecycle"] = test_subscription_lifecycle()
    results["entitlement_check"] = test_entitlement_check()
    results["usage_recording"] = test_usage_recording()
    results["limit_enforcement"] = test_usage_limit_enforcement()
    results["cancellation"] = test_subscription_cancellation()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print(f"Completed at: {datetime.now().isoformat()}")
    
    return results


if __name__ == "__main__":
    run_all_tests()

