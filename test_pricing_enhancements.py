#!/usr/bin/env python3
"""
Test Script for ZeroQue Pricing Service V2 Enhancements
Tests the new multi-provider integration, billing analytics, security, and event retry features
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

class PricingEnhancementTester:
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
    
    async def test_multi_provider_configuration(self) -> bool:
        """Test multi-provider configuration with zeroque_rails"""
        print("\n⚙️ Testing multi-provider configuration...")
        
        tenant_id = str(uuid.uuid4())
        
        # Configure external pricing provider
        provider_config = {
            "tenant_id": tenant_id,
            "provider_name": "external_pricing_engine",
            "config": {
                "api_url": "https://external-pricing.example.com/api/v1",
                "api_key": "sk_test_external_key",
                "timeout_seconds": 30,
                "retry_attempts": 3,
                "custom_config": {
                    "algorithm": "dynamic_pricing",
                    "fallback_enabled": True
                }
            }
        }
        
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/admin/rails/pricing",
                json=provider_config,
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                print(f"  ✅ External pricing provider configured for tenant: {tenant_id}")
                self.test_data["tenant_id"] = tenant_id
                return True
            else:
                print(f"  ❌ Provider configuration failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Provider configuration error: {str(e)}")
            return False
    
    async def test_external_price_calculation(self) -> bool:
        """Test external price calculation with fallback"""
        print("\n💰 Testing external price calculation...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for external price calculation")
            return False
        
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/external/calculate-price",
                params={
                    "store_id": "store_123",
                    "offer_id": "offer_456",
                    "user_id": "user_789",
                    "currency": "GBP"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_user",
                    "x-user-role": "user"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ External price calculation successful")
                print(f"  💵 Price: £{result.get('price_minor', 0) / 100:.2f}")
                print(f"  🔧 Provider: {result.get('provider', 'N/A')}")
                print(f"  📍 Source: {result.get('source', 'N/A')}")
                return True
            else:
                print(f"  ❌ External price calculation failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ External price calculation error: {str(e)}")
            return False
    
    async def test_billing_analytics_reports(self) -> bool:
        """Test billing analytics and cost breakdowns"""
        print("\n📊 Testing billing analytics reports...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for billing analytics")
            return False
        
        # Test reports for the last 30 days
        end_date = datetime.now().date()
        start_date = end_date.replace(day=1)  # Start of current month
        
        try:
            # Test tenant-level reports
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports",
                params={
                    "tenant_id": tenant_id,
                    "period_start": start_date.isoformat(),
                    "period_end": end_date.isoformat(),
                    "currency": "GBP",
                    "group_by": "tenant"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Billing analytics reports generated")
                print(f"  📈 Period: {result.get('period', {}).get('start')} to {result.get('period', {}).get('end')}")
                print(f"  📊 Group by: {result.get('period', {}).get('group_by')}")
                
                summary = result.get("summary", [])
                if summary:
                    print(f"  📅 Daily trends: {len(summary)} days")
                    for day_data in summary[:3]:  # Show first 3 days
                        date = day_data.get("date", "N/A")
                        count = day_data.get("calculations_count", 0)
                        total = day_data.get("total_final_price_minor", 0)
                        print(f"    {date}: {count} calculations, £{total/100:.2f}")
                
                rule_usage = result.get("rule_usage", [])
                if rule_usage:
                    print(f"  🔧 Rule usage: {len(rule_usage)} rules")
                    for rule in rule_usage[:3]:  # Show top 3 rules
                        name = rule.get("rule_name", "N/A")
                        usage = rule.get("usage_count", 0)
                        print(f"    {name}: {usage} times")
                
                return True
            else:
                print(f"  ❌ Billing analytics failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Billing analytics error: {str(e)}")
            return False
    
    async def test_feature_level_analytics(self) -> bool:
        """Test feature-level analytics grouping"""
        print("\n🎯 Testing feature-level analytics...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for feature analytics")
            return False
        
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports",
                params={
                    "tenant_id": tenant_id,
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07",
                    "currency": "GBP",
                    "group_by": "feature"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Feature-level analytics generated")
                
                summary = result.get("summary", [])
                if summary:
                    print(f"  🏪 Store-level breakdown: {len(summary)} stores")
                    for store_data in summary[:3]:  # Show top 3 stores
                        store_id = store_data.get("store_id", "N/A")
                        count = store_data.get("calculations_count", 0)
                        total = store_data.get("total_final_price_minor", 0)
                        print(f"    {store_id}: {count} calculations, £{total/100:.2f}")
                
                return True
            else:
                print(f"  ❌ Feature analytics failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Feature analytics error: {str(e)}")
            return False
    
    async def test_security_permissions(self) -> bool:
        """Test security and permission checks"""
        print("\n🔒 Testing security and permissions...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for security testing")
            return False
        
        # Test admin permissions
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/pricebooks",
                json={
                    "name": "Test Pricebook",
                    "description": "Test pricebook for security testing",
                    "pricebook_type": "standard",
                    "currency": "GBP",
                    "tenant_id": tenant_id
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                print("  ✅ Admin permissions: Can create pricebooks")
            else:
                print(f"  ⚠️ Admin permissions: Unexpected status {response.status_code}")
        
        # Test manager permissions
        try:
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports",
                params={
                    "tenant_id": tenant_id,
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07",
                    "currency": "GBP"
                },
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_manager",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code == 200:
                print("  ✅ Manager permissions: Can view reports")
            else:
                print(f"  ❌ Manager permissions: Failed to view reports ({response.status_code})")
                return False
        
        # Test user permissions (should be limited)
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/admin/rails/pricing",
                json={"tenant_id": tenant_id},
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_user",
                    "x-user-role": "user"
                }
            )
            
            if response.status_code == 403:
                print("  ✅ User permissions: Correctly restricted from admin operations")
                return True
            else:
                print(f"  ❌ User permissions: Should be restricted but got {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Security testing error: {str(e)}")
            return False
    
    async def test_event_retry_mechanism(self) -> bool:
        """Test event retry mechanism"""
        print("\n🔄 Testing event retry mechanism...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for event retry testing")
            return False
        
        try:
            response = await self.client.post(
                f"{PRICING_SERVICE}/pricing/v2/events/retry",
                params={"max_events": 50},
                headers={
                    "x-tenant-id": tenant_id,
                    "x-user-id": "test_admin",
                    "x-user-role": "admin"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                processed = result.get("processed_events", 0)
                failed = result.get("failed_events", 0)
                print(f"  ✅ Event retry mechanism working")
                print(f"  📤 Processed events: {processed}")
                print(f"  ❌ Failed events: {failed}")
                print(f"  ⏰ Timestamp: {result.get('timestamp', 'N/A')}")
                return True
            else:
                print(f"  ❌ Event retry failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Event retry testing error: {str(e)}")
            return False
    
    async def test_error_scenarios(self) -> bool:
        """Test error scenarios and edge cases"""
        print("\n🚨 Testing error scenarios...")
        
        try:
            # Test invalid tenant_id
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports",
                params={
                    "tenant_id": "invalid-uuid",
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07"
                },
                headers={
                    "x-tenant-id": "invalid-uuid",
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code in [400, 422]:
                print("  ✅ Invalid tenant_id properly rejected")
            else:
                print(f"  ❌ Invalid tenant_id not properly handled: {response.status_code}")
                return False
            
            # Test missing required parameters
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports",
                params={
                    "tenant_id": str(uuid.uuid4()),
                    "period_start": "2025-10-01"
                    # Missing period_end
                },
                headers={
                    "x-tenant-id": str(uuid.uuid4()),
                    "x-user-role": "manager"
                }
            )
            
            if response.status_code in [400, 422]:
                print("  ✅ Missing required parameters properly rejected")
            else:
                print(f"  ❌ Missing parameters not properly handled: {response.status_code}")
                return False
            
            # Test unauthorized access
            response = await self.client.get(
                f"{PRICING_SERVICE}/pricing/v2/reports",
                params={
                    "tenant_id": str(uuid.uuid4()),
                    "period_start": "2025-10-01",
                    "period_end": "2025-10-07"
                },
                headers={
                    "x-tenant-id": str(uuid.uuid4()),
                    "x-user-role": "user"  # User should not have access to reports
                }
            )
            
            if response.status_code == 403:
                print("  ✅ Unauthorized access properly rejected")
            else:
                print(f"  ❌ Unauthorized access not properly handled: {response.status_code}")
                return False
            
            return True
            
        except Exception as e:
            print(f"  ❌ Error scenario testing failed: {str(e)}")
            return False
    
    async def run_comprehensive_test(self):
        """Run all pricing enhancement tests"""
        print("🚀 Starting Comprehensive Pricing Service Enhancement Tests")
        print("=" * 70)
        
        # Health check
        if not await self.health_check_pricing_service():
            print("\n❌ Pricing service is not healthy. Please start the service before running tests.")
            return False
        
        print("\n✅ Pricing service is healthy. Proceeding with enhancement tests...")
        
        # Run all tests
        tests = [
            ("Multi-Provider Configuration", self.test_multi_provider_configuration),
            ("External Price Calculation", self.test_external_price_calculation),
            ("Billing Analytics Reports", self.test_billing_analytics_reports),
            ("Feature-Level Analytics", self.test_feature_level_analytics),
            ("Security and Permissions", self.test_security_permissions),
            ("Event Retry Mechanism", self.test_event_retry_mechanism),
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
        print("🎉 Pricing Service Enhancement Tests Completed!")
        print(f"📊 Results: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎯 All tests passed! Pricing service enhancements are working correctly.")
        else:
            print("⚠️ Some tests failed. Please review the output above.")
        
        print(f"\n📝 Test data created:")
        print(f"   Tenant ID: {self.test_data.get('tenant_id', 'N/A')}")
        
        return passed_tests == total_tests

async def main():
    """Main test runner"""
    async with PricingEnhancementTester() as tester:
        success = await tester.run_comprehensive_test()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
