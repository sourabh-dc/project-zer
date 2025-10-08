#!/usr/bin/env python3
"""
Test Script for ZeroQue Pricing Service Integration
Tests the comprehensive reports and service integrations
"""

import asyncio
import httpx
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List
import sys

# Service URLs
PRICING_SERVICE = "http://localhost:8082"

class PricingIntegrationTester:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.test_results = {}
        self.test_data = {}
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def health_check_pricing_service(self) -> bool:
        """Check health of pricing service"""
        print("🔍 Checking health of Pricing Service...")
        
        try:
            response = await self.client.get(f"{PRICING_SERVICE}/health")
            if response.status_code == 200:
                print("  ✅ Pricing Service: Healthy")
                return True
            else:
                print(f"  ❌ Pricing Service: Unhealthy ({response.status_code})")
                return False
        except Exception as e:
            print(f"  ❌ Pricing Service: Unreachable ({str(e)})")
            return False
    
    async def test_comprehensive_reports(self) -> bool:
        """Test all comprehensive reports"""
        print("\n📊 Testing Comprehensive Reports...")
        
        tenant_id = str(uuid.uuid4())
        self.test_data["tenant_id"] = tenant_id
        
        # Test Tenant Entitlement Matrix Report
        print("\n  🏢 Testing Tenant Entitlement Matrix Report...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/tenant-entitlement-matrix",
                params={"tenant_id": tenant_id},
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Tenant Entitlement Matrix: Generated successfully")
                print(f"    📈 Summary: {result.get('summary', {})}")
                print(f"    📋 Matrix entries: {result.get('total_entries', 0)}")
            else:
                print(f"    ❌ Tenant Entitlement Matrix failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Tenant Entitlement Matrix error: {str(e)}")
            return False
        
        # Test Usage Cost Breakdown Report
        print("\n  💰 Testing Usage Cost Breakdown Report...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/usage-cost-breakdown",
                params={
                    "tenant_id": tenant_id,
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07",
                    "feature_code": "api_calls"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Usage Cost Breakdown: Generated successfully")
                print(f"    💵 Total cost: £{result.get('summary', {}).get('total_cost_minor', 0) / 100:.2f}")
                print(f"    📊 Features analyzed: {result.get('summary', {}).get('total_features', 0)}")
            else:
                print(f"    ❌ Usage Cost Breakdown failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Usage Cost Breakdown error: {str(e)}")
            return False
        
        # Test Active Subscriptions & Invoices Report
        print("\n  📋 Testing Active Subscriptions & Invoices Report...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/active-subscriptions-invoices",
                params={"tenant_id": tenant_id},
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Active Subscriptions & Invoices: Generated successfully")
                print(f"    📈 Active subscriptions: {result.get('summary', {}).get('active_subscriptions', 0)}")
                print(f"    💰 Total revenue: £{result.get('summary', {}).get('total_revenue_minor', 0) / 100:.2f}")
            else:
                print(f"    ❌ Active Subscriptions & Invoices failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Active Subscriptions & Invoices error: {str(e)}")
            return False
        
        # Test Discount/Promo Impact Report
        print("\n  🎯 Testing Discount/Promo Impact Report...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/discount-promo-impact",
                params={
                    "tenant_id": tenant_id,
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Discount/Promo Impact: Generated successfully")
                print(f"    💸 Total discount: £{result.get('summary', {}).get('total_discount_minor', 0) / 100:.2f}")
                print(f"    📊 Promotions/rules: {result.get('summary', {}).get('total_promotions_rules', 0)}")
            else:
                print(f"    ❌ Discount/Promo Impact failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Discount/Promo Impact error: {str(e)}")
            return False
        
        # Test Price Change Audit Report
        print("\n  🔍 Testing Price Change Audit Report...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/price-change-audit",
                params={
                    "tenant_id": tenant_id,
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Price Change Audit: Generated successfully")
                print(f"    📈 Price change events: {result.get('summary', {}).get('total_price_change_events', 0)}")
                print(f"    📋 Audit entries: {result.get('summary', {}).get('total_audit_entries', 0)}")
            else:
                print(f"    ❌ Price Change Audit failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Price Change Audit error: {str(e)}")
            return False
        
        # Test Overage Alerts Report
        print("\n  ⚠️ Testing Overage Alerts Report...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/overage-alerts",
                params={
                    "tenant_id": tenant_id,
                    "threshold_percentage": 80.0
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Overage Alerts: Generated successfully")
                print(f"    🚨 Critical alerts: {result.get('summary', {}).get('critical_alerts', 0)}")
                print(f"    ⚠️ Warning alerts: {result.get('summary', {}).get('warning_alerts', 0)}")
            else:
                print(f"    ❌ Overage Alerts failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Overage Alerts error: {str(e)}")
            return False
        
        return True
    
    async def test_service_integrations(self) -> bool:
        """Test service integration endpoints"""
        print("\n🔗 Testing Service Integrations...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for integration testing")
            return False
        
        # Test Catalog Integration - Product Created Event
        print("\n  📦 Testing Catalog Integration (Product Created)...")
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/integration/catalog/product-created",
                json={
                    "tenant_id": tenant_id,
                    "product_id": str(uuid.uuid4()),
                    "offer_id": str(uuid.uuid4()),
                    "base_price_minor": 2500,
                    "currency": "GBP"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Product Created Event: Handled successfully")
                print(f"    📝 Message: {result.get('message', 'N/A')}")
            else:
                print(f"    ❌ Product Created Event failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Product Created Event error: {str(e)}")
            return False
        
        # Test Subscriptions Integration - Plan Changed Event
        print("\n  📋 Testing Subscriptions Integration (Plan Changed)...")
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/integration/subscriptions/plan-changed",
                json={
                    "tenant_id": tenant_id,
                    "old_plan_code": "basic",
                    "new_plan_code": "premium"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_user",
                    "x-user-role": "user"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Plan Changed Event: Handled successfully")
                print(f"    📝 Message: {result.get('message', 'N/A')}")
            else:
                print(f"    ❌ Plan Changed Event failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Plan Changed Event error: {str(e)}")
            return False
        
        # Test Orders Integration - Resolve Prices
        print("\n  🛒 Testing Orders Integration (Resolve Prices)...")
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/integration/orders/resolve-prices",
                json={
                    "tenant_id": tenant_id,
                    "items": [
                        {
                            "offer_id": str(uuid.uuid4()),
                            "quantity": 2,
                            "store_id": str(uuid.uuid4())
                        },
                        {
                            "offer_id": str(uuid.uuid4()),
                            "quantity": 1,
                            "store_id": str(uuid.uuid4())
                        }
                    ],
                    "currency": "GBP",
                    "user_id": str(uuid.uuid4())
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_user",
                    "x-user-role": "user"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Price Resolution: Successful")
                print(f"    💰 Total price: £{result.get('total_price_minor', 0) / 100:.2f}")
                print(f"    📦 Items resolved: {len(result.get('resolved_items', []))}")
            else:
                print(f"    ❌ Price Resolution failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Price Resolution error: {str(e)}")
            return False
        
        # Test Billing Integration - Calculate Usage Costs
        print("\n  💳 Testing Billing Integration (Calculate Usage Costs)...")
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/integration/billing/calculate-usage-costs",
                json={
                    "tenant_id": tenant_id,
                    "usage_entries": [
                        {
                            "feature_code": "api_calls",
                            "amount": 1000,
                            "type": "count"
                        },
                        {
                            "feature_code": "storage",
                            "amount": 5000,
                            "type": "mb"
                        }
                    ],
                    "currency": "GBP"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Usage Cost Calculation: Successful")
                print(f"    💰 Total cost: £{result.get('total_cost_minor', 0) / 100:.2f}")
                print(f"    📊 Cost breakdown items: {len(result.get('cost_breakdown', []))}")
            else:
                print(f"    ❌ Usage Cost Calculation failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Usage Cost Calculation error: {str(e)}")
            return False
        
        # Test Usage Integration - Overage Check
        print("\n  📊 Testing Usage Integration (Overage Check)...")
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/integration/usage/overage-check",
                json={
                    "tenant_id": tenant_id,
                    "feature_code": "api_calls",
                    "current_usage": 850,
                    "threshold_percentage": 80.0
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Overage Check: Successful")
                print(f"    🚨 Overage detected: {result.get('overage_detected', False)}")
                print(f"    ⚠️ Alert level: {result.get('alert_level', 'info')}")
            else:
                print(f"    ❌ Overage Check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Overage Check error: {str(e)}")
            return False
        
        # Test Integration Status
        print("\n  📈 Testing Integration Status...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/integration/status",
                params={"tenant_id": tenant_id},
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"    ✅ Integration Status: Retrieved successfully")
                integration_status = result.get('integration_status', {})
                print(f"    🔗 Connected services: {len([s for s in integration_status.values() if s.get('connected')])}")
            else:
                print(f"    ❌ Integration Status failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Integration Status error: {str(e)}")
            return False
        
        return True
    
    async def test_error_scenarios(self) -> bool:
        """Test error scenarios and edge cases"""
        print("\n🚨 Testing Error Scenarios...")
        
        tenant_id = str(uuid.uuid4())
        
        # Test invalid tenant_id
        print("\n  ❌ Testing invalid tenant_id...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/tenant-entitlement-matrix",
                params={"tenant_id": "invalid-uuid"},
                headers={
                    "x-tenant-id": "invalid-uuid",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code in [400, 422]:
                print("    ✅ Invalid tenant_id properly rejected")
            else:
                print(f"    ❌ Invalid tenant_id not properly handled: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Invalid tenant_id testing error: {str(e)}")
            return False
        
        # Test unauthorized access
        print("\n  🔒 Testing unauthorized access...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/tenant-entitlement-matrix",
                params={"tenant_id": tenant_id},
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-role": "user"  # User should not have access to reports
                }
            )
            
            if response.status_code == 403:
                print("    ✅ Unauthorized access properly rejected")
            else:
                print(f"    ❌ Unauthorized access not properly handled: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Unauthorized access testing error: {str(e)}")
            return False
        
        # Test missing required parameters
        print("\n  📝 Testing missing required parameters...")
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports/usage-cost-breakdown",
                params={
                    "tenant_id": tenant_id,
                    "period_start": "2025-10-01"
                    # Missing period_end
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code in [400, 422]:
                print("    ✅ Missing parameters properly rejected")
            else:
                print(f"    ❌ Missing parameters not properly handled: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Missing parameters testing error: {str(e)}")
            return False
        
        return True
    
    async def run_comprehensive_test(self):
        """Run all pricing integration tests"""
        print("🚀 Starting Comprehensive Pricing Service Integration Tests")
        print("=" * 70)
        
        # Health check
        if not await self.health_check_pricing_service():
            print("\n❌ Pricing service is not healthy. Please start the service before running tests.")
            return False
        
        print("\n✅ Pricing service is healthy. Proceeding with integration tests...")
        
        # Run all tests
        tests = [
            ("Comprehensive Reports", self.test_comprehensive_reports),
            ("Service Integrations", self.test_service_integrations),
            ("Error Scenarios", self.test_error_scenarios)
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test_name, test_func in tests:
            try:
                result = await test_func()
                if result:
                    passed_tests += 1
                    print(f"  ✅ {test_name}: PASSED")
                else:
                    print(f"  ❌ {test_name}: FAILED")
            except Exception as e:
                print(f"  ❌ {test_name}: ERROR - {str(e)}")
        
        print("\n" + "=" * 70)
        print("🎉 Pricing Service Integration Tests Completed!")
        print(f"📊 Results: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎯 All tests passed! Pricing service integration is working correctly.")
        else:
            print("⚠️ Some tests failed. Please review the output above.")
        
        print(f"\n📝 Test data created:")
        print(f"   Tenant ID: {self.test_data.get('tenant_id', 'N/A')}")
        
        return passed_tests == total_tests

async def main():
    """Main test runner"""
    async with PricingIntegrationTester() as tester:
        success = await tester.run_comprehensive_test()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
