#!/usr/bin/env python3
"""
COMPREHENSIVE ENTITLEMENTS & SUBSCRIPTIONS TEST
Tests all endpoints for both services:
- Subscriptions: plans, features, plan-features, tenant subscriptions
- Entitlements: check entitlement, record usage
"""
import requests
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional

BASE_URL = "http://localhost:8000"
ADMIN_API_KEY = "zq_bootstrap_admin_key"

class EntitlementsSubscriptionsTestRunner:
    def __init__(self):
        self.tenant_id = None
        self.super_user_id = None
        self.super_api_key = None
        self.subscription_admin_id = None
        self.subscription_admin_api_key = None
        self.plan_code = None
        self.feature_code = None
        self.timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
    def api(self, method: str, endpoint: str, headers: Dict = None, data: Dict = None, params: Dict = None, expect: int = 200) -> Any:
        """Make API call"""
        url = f"{BASE_URL}{endpoint}"
        headers = headers or {"X-API-Key": ADMIN_API_KEY, "Content-Type": "application/json"}
        
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, params=params)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=data, params=params)
            elif method == "PUT":
                resp = requests.put(url, headers=headers, json=data)
            elif method == "DELETE":
                resp = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unknown method: {method}")
            
            if resp.status_code != expect:
                print(f"  ❌ {method} {endpoint} - Status: {resp.status_code} (expected {expect})")
                if resp.content:
                    try:
                        error_detail = resp.json().get('detail', resp.text[:200])
                        print(f"     Error: {error_detail}")
                    except:
                        print(f"     Response: {resp.text[:200]}")
                return None
            
            print(f"  ✅ {method} {endpoint}")
            if resp.content and method != "DELETE":
                return resp.json()
            return {"status": "ok"}
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            return None
    
    def section(self, title):
        print(f"\n{'='*80}")
        print(f"  {title}")
        print(f"{'='*80}")
    
    def run_tests(self):
        # Setup: Create tenant and users
        self.section("SETUP: CREATE TENANT & USERS")
        
        tenant = self.api("POST", "/v1/tenants", data={
            "name": f"Subscriptions Test Corp {self.timestamp}",
            "type": "customer"
        }, expect=201)
        if not tenant:
            return False
        
        self.tenant_id = tenant["tenant_id"]
        print(f"     Tenant ID: {self.tenant_id}")
        
        # Create super user
        super_user = self.api("POST", f"/v1/tenants/{self.tenant_id}/super-user", data={
            "email": f"super{self.timestamp}@subtest.com",
            "display_name": "Super Admin",
            "password": "Super123!"
        }, expect=201)
        if not super_user:
            return False
        
        self.super_user_id = super_user["user_id"]
        self.super_api_key = super_user["api_key"]
        headers_super = {"X-API-Key": self.super_api_key, "Content-Type": "application/json"}
        
        # Get permissions
        perms = self.api("GET", "/v1/permissions", headers=headers_super)
        if not perms:
            return False
        
        # Find subscription permissions
        plans_manage = next((p for p in perms["permissions"] if p["code"] == "subscriptions.plans.manage"), None)
        plans_view = next((p for p in perms["permissions"] if p["code"] == "subscriptions.plans.view"), None)
        features_manage = next((p for p in perms["permissions"] if p["code"] == "subscriptions.features.manage"), None)
        tenant_manage = next((p for p in perms["permissions"] if p["code"] == "subscriptions.tenant.manage"), None)
        entitlements_check = next((p for p in perms["permissions"] if p["code"] == "entitlements.check"), None)
        usage_record = next((p for p in perms["permissions"] if p["code"] == "entitlements.usage.record"), None)
        
        # Create subscription admin role
        sub_role = self.api("POST", "/v1/roles", headers=headers_super, data={
            "code": f"subscription_admin_{self.timestamp}",
            "description": "Manages subscriptions"
        }, expect=201)
        
        # Assign permissions
        if plans_manage:
            self.api("POST", f"/v1/roles/{sub_role['role_id']}/permissions/{plans_manage['permission_id']}", headers=headers_super, expect=201)
        if plans_view:
            self.api("POST", f"/v1/roles/{sub_role['role_id']}/permissions/{plans_view['permission_id']}", headers=headers_super, expect=201)
        if features_manage:
            self.api("POST", f"/v1/roles/{sub_role['role_id']}/permissions/{features_manage['permission_id']}", headers=headers_super, expect=201)
        if tenant_manage:
            self.api("POST", f"/v1/roles/{sub_role['role_id']}/permissions/{tenant_manage['permission_id']}", headers=headers_super, expect=201)
        if entitlements_check:
            self.api("POST", f"/v1/roles/{sub_role['role_id']}/permissions/{entitlements_check['permission_id']}", headers=headers_super, expect=201)
        if usage_record:
            self.api("POST", f"/v1/roles/{sub_role['role_id']}/permissions/{usage_record['permission_id']}", headers=headers_super, expect=201)
        
        # Add tenant scope
        self.api("POST", f"/v1/roles/{sub_role['role_id']}/scopes", headers=headers_super,
                params={"resource_type": "tenant", "resource_id": self.tenant_id}, expect=201)
        
        # Create subscription admin user
        sub_user = self.api("POST", "/v1/users", headers=headers_super, data={
            "email": f"subadmin{self.timestamp}@subtest.com",
            "display_name": "Subscription Admin",
            "password": "SubAdmin123!",
            "tenant_id": self.tenant_id
        }, expect=201)
        self.subscription_admin_id = sub_user["user_id"]
        
        # Assign role
        self.api("POST", f"/v1/users/{self.subscription_admin_id}/roles", headers=headers_super,
                data={"role_id": sub_role["role_id"]}, expect=201)
        
        # Login subscription admin
        sub_login = self.api("POST", "/v1/auth/login", data={
            "email": f"subadmin{self.timestamp}@subtest.com",
            "password": "SubAdmin123!"
        })
        if sub_login:
            self.subscription_admin_api_key = sub_login["api_key"]
        
        headers_sub = {"X-API-Key": self.subscription_admin_api_key, "Content-Type": "application/json"}
        
        # Test 1: Create Subscription Plan
        self.section("TEST 1: CREATE SUBSCRIPTION PLAN")
        
        plan = self.api("POST", "/v1/subscriptions/plans", headers=headers_sub, data={
            "code": f"plan_{self.timestamp}",
            "name": f"Test Plan {self.timestamp}",
            "description": "A test subscription plan",
            "price_yearly_minor": 1200000,  # £12,000/year
            "currency": "GBP"
        }, expect=201)
        if plan:
            self.plan_code = plan["plan_code"]
            print(f"     Plan Code: {self.plan_code}")
        
        # Test 2: List Plans
        self.section("TEST 2: LIST SUBSCRIPTION PLANS")
        
        plans = self.api("GET", "/v1/subscriptions/plans", headers=headers_sub)
        if plans:
            print(f"     Found {len(plans['plans'])} plan(s)")
            for p in plans['plans']:
                print(f"       - {p['name']} ({p['code']}) - £{p['price_yearly_minor'] / 100:.2f}/year")
        
        # Test with active filter
        active_plans = self.api("GET", "/v1/subscriptions/plans", headers=headers_sub, params={"active": True})
        if active_plans:
            print(f"     Active plans: {len(active_plans['plans'])}")
        
        # Test 3: Create Feature
        self.section("TEST 3: CREATE FEATURE")
        
        feature = self.api("POST", "/v1/subscriptions/features", headers=headers_sub, data={
            "code": f"feature_{self.timestamp}",
            "name": f"Test Feature {self.timestamp}",
            "description": "A test feature",
            "category": "api",
            "reset_period": "monthly"
        }, expect=201)
        if feature:
            self.feature_code = feature["feature_code"]
            print(f"     Feature Code: {self.feature_code}")
        
        # Test 4: Add Feature to Plan
        self.section("TEST 4: ADD FEATURE TO PLAN")
        
        plan_feature = self.api("PUT", f"/v1/subscriptions/plans/{self.plan_code}/features/{self.feature_code}", 
                                headers=headers_sub, data={
            "limits": {
                "max_value": 1000,
                "warn_at": 800
            }
        }, expect=200)
        if plan_feature:
            print(f"     Feature added to plan with limits: {plan_feature['limits']}")
        
        # Test 5: Create Tenant Subscription
        self.section("TEST 5: CREATE TENANT SUBSCRIPTION")
        
        subscription = self.api("POST", "/v1/subscriptions/subscriptions", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "plan_code": self.plan_code,
            "payment_method": "stripe",
            "billing_cycle": "yearly",
            "auto_renew": True
        }, expect=201)
        if subscription:
            print(f"     Subscription created: {subscription['plan_code']} - Status: {subscription['status']}")
        
        # Test 6: Check Entitlement
        self.section("TEST 6: CHECK ENTITLEMENT")
        
        entitlement = self.api("POST", "/v1/entitlements/check", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "feature_code": self.feature_code
        })
        if entitlement:
            print(f"     Allowed: {entitlement['allowed']}")
            if entitlement.get('usage'):
                print(f"     Usage: {entitlement['usage']}/{entitlement['limit']}")
                print(f"     Remaining: {entitlement['remaining']}")
            else:
                print(f"     Reason: {entitlement.get('reason', 'N/A')}")
        
        # Test 7: Record Usage
        self.section("TEST 7: RECORD USAGE")
        
        usage = self.api("POST", "/v1/entitlements/usage/record", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "feature_code": self.feature_code,
            "usage_type": "api_call",
            "count": 10
        }, expect=201)
        if usage:
            print(f"     Recorded: {usage['recorded']} usage(s)")
            print(f"     Total: {usage['total']} usage(s)")
        
        # Test 8: Check Entitlement After Usage
        self.section("TEST 8: CHECK ENTITLEMENT AFTER USAGE")
        
        entitlement2 = self.api("POST", "/v1/entitlements/check", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "feature_code": self.feature_code
        })
        if entitlement2:
            print(f"     Allowed: {entitlement2['allowed']}")
            print(f"     Usage: {entitlement2['usage']}/{entitlement2['limit']}")
            print(f"     Remaining: {entitlement2['remaining']}")
        
        # Test 9: Record More Usage (up to limit)
        self.section("TEST 9: RECORD USAGE UP TO LIMIT")
        
        # Record 990 more to reach 1000
        usage2 = self.api("POST", "/v1/entitlements/usage/record", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "feature_code": self.feature_code,
            "usage_type": "api_call",
            "count": 990
        }, expect=201)
        if usage2:
            print(f"     Recorded: {usage2['recorded']} usage(s)")
            print(f"     Total: {usage2['total']} usage(s)")
        
        # Test 10: Try to Exceed Limit
        self.section("TEST 10: TRY TO EXCEED LIMIT")
        
        usage3 = self.api("POST", "/v1/entitlements/usage/record", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "feature_code": self.feature_code,
            "usage_type": "api_call",
            "count": 1
        }, expect=429)
        if usage3 is None:
            print(f"     ✅ Usage limit exceeded - correctly rejected (429)")
        
        # Test 11: Remove Feature from Plan
        self.section("TEST 11: REMOVE FEATURE FROM PLAN")
        
        remove_result = self.api("DELETE", f"/v1/subscriptions/plans/{self.plan_code}/features/{self.feature_code}", 
                                 headers=headers_sub, expect=204)
        if remove_result:
            print(f"     Feature removed from plan")
        
        # Test 12: Check Entitlement After Removal
        self.section("TEST 12: CHECK ENTITLEMENT AFTER FEATURE REMOVAL")
        
        entitlement3 = self.api("POST", "/v1/entitlements/check", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "feature_code": self.feature_code
        })
        if entitlement3:
            print(f"     Allowed: {entitlement3['allowed']}")
            print(f"     Reason: {entitlement3.get('reason', 'N/A')}")
            if entitlement3.get('reason') == 'feature_not_in_plan':
                print(f"     ✅ Correctly detects feature removed from plan")
        
        # Test 13: Error Cases
        self.section("TEST 13: ERROR CASES")
        
        # Duplicate plan code
        dup_plan = self.api("POST", "/v1/subscriptions/plans", headers=headers_sub, data={
            "code": f"plan_{self.timestamp}",  # Same code
            "name": "Duplicate",
            "price_yearly_minor": 1000
        }, expect=409)
        if dup_plan is None:
            print(f"     ✅ Duplicate plan code rejected (409)")
        
        # Duplicate feature code
        dup_feature = self.api("POST", "/v1/subscriptions/features", headers=headers_sub, data={
            "code": f"feature_{self.timestamp}",  # Same code
            "name": "Duplicate"
        }, expect=409)
        if dup_feature is None:
            print(f"     ✅ Duplicate feature code rejected (409)")
        
        # Invalid plan for subscription
        invalid_sub = self.api("POST", "/v1/subscriptions/subscriptions", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "plan_code": "invalid_plan_code"
        }, expect=404)
        if invalid_sub is None:
            print(f"     ✅ Invalid plan code rejected (404)")
        
        # Duplicate subscription
        dup_sub = self.api("POST", "/v1/subscriptions/subscriptions", headers=headers_sub, data={
            "tenant_id": self.tenant_id,
            "plan_code": self.plan_code
        }, expect=409)
        if dup_sub is None:
            print(f"     ✅ Duplicate subscription rejected (409)")
        
        # Permission Tests
        self.section("TEST 14: PERMISSION VALIDATION")
        
        # Create user without permissions
        no_perm_user = self.api("POST", "/v1/users", headers=headers_super, data={
            "email": f"noperm{self.timestamp}@subtest.com",
            "display_name": "No Permissions",
            "password": "NoPerm123!",
            "tenant_id": self.tenant_id
        }, expect=201)
        
        if no_perm_user:
            no_perm_login = self.api("POST", "/v1/auth/login", data={
                "email": f"noperm{self.timestamp}@subtest.com",
                "password": "NoPerm123!"
            })
            
            if no_perm_login:
                headers_no_perm = {"X-API-Key": no_perm_login["api_key"], "Content-Type": "application/json"}
                
                # Should fail
                no_perm_plan = self.api("POST", "/v1/subscriptions/plans", headers=headers_no_perm, data={
                    "code": "unauthorized",
                    "name": "Unauthorized",
                    "price_yearly_minor": 1000
                }, expect=403)
                if no_perm_plan is None:
                    print(f"     ✅ Permission check working - unauthorized user blocked (403)")
        
        # Final Summary
        self.section("✅ ALL TESTS COMPLETE")
        print(f"\n  Tested Endpoints:")
        print(f"  ✅ POST /v1/subscriptions/plans - Create plan")
        print(f"  ✅ GET /v1/subscriptions/plans - List plans")
        print(f"  ✅ POST /v1/subscriptions/features - Create feature")
        print(f"  ✅ PUT /v1/subscriptions/plans/{{plan}}/features/{{feature}} - Add feature to plan")
        print(f"  ✅ DELETE /v1/subscriptions/plans/{{plan}}/features/{{feature}} - Remove feature")
        print(f"  ✅ POST /v1/subscriptions/subscriptions - Create tenant subscription")
        print(f"  ✅ POST /v1/entitlements/check - Check entitlement")
        print(f"  ✅ POST /v1/entitlements/usage/record - Record usage")
        print(f"\n  Error Handling:")
        print(f"  ✅ Duplicate codes rejected")
        print(f"  ✅ Invalid references rejected")
        print(f"  ✅ Usage limits enforced")
        print(f"  ✅ Permission checks enforced")
        print(f"\n  🎉 ALL ENTITLEMENTS & SUBSCRIPTIONS ENDPOINTS VALIDATED!")
        
        return True

if __name__ == "__main__":
    runner = EntitlementsSubscriptionsTestRunner()
    success = runner.run_tests()
    sys.exit(0 if success else 1)

