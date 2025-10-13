#!/usr/bin/env python3
"""
Comprehensive Test Script for ZeroQue Payments Service V2
Tests all payment functionality, integrations, and scenarios
"""

import asyncio
import httpx
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List
import sys

# Service URLs
PAYMENTS_SERVICE = "http://localhost:8087"
INTEGRATED_SERVICES = {
    "orders": "http://localhost:8081",
    "billing": "http://localhost:8083", 
    "ledger": "http://localhost:8086",
    "notifications": "http://localhost:8087"
}

class PaymentsServiceTester:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.test_results = {}
        self.test_data = {}
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def health_check_payments_service(self) -> bool:
        """Check health of payments service"""
        print("🔍 Checking health of Payments Service...")
        
        try:
            response = await self.client.get(f"{PAYMENTS_SERVICE}/health")
            if response.status_code == 200:
                print("  ✅ Payments Service: Healthy")
                return True
            else:
                print(f"  ❌ Payments Service: Unhealthy ({response.status_code})")
                return False
        except Exception as e:
            print(f"  ❌ Payments Service: Unreachable ({str(e)})")
            return False
    
    async def test_provider_configuration(self) -> bool:
        """Test payment provider configuration"""
        print("\n⚙️ Testing provider configuration...")
        
        tenant_id = str(uuid.uuid4())
        
        # Configure Stripe provider
        stripe_config = {
            "tenant_id": tenant_id,
            "type": "payment",
            "name": "stripe",
            "config": {
                "api_key": "sk_test_demo_key",
                "webhook_secret": "whsec_demo_secret",
                "base_url": "https://api.stripe.com/v1"
            },
            "active": True
        }
        
        try:
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/admin/rails/payment",
                json=stripe_config,
                headers={"x-tenant-id": tenant_id}
            )
            
            if response.status_code == 200:
                print(f"  ✅ Stripe provider configured for tenant: {tenant_id}")
                self.test_data["tenant_id"] = tenant_id
                return True
            else:
                print(f"  ❌ Provider configuration failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Provider configuration error: {str(e)}")
            return False
    
    async def test_customer_creation(self) -> str:
        """Test customer creation"""
        print("\n👤 Testing customer creation...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for customer creation")
            return None
        
        customer_data = {
            "tenant_id": tenant_id,
            "provider": "stripe",
            "email": f"testcustomer_{datetime.now().strftime('%H%M%S')}@example.com",
            "name": "Test Customer",
            "metadata": {"phone": "+44123456789", "source": "test"}
        }
        
        try:
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/customers",
                json=customer_data,
                headers={"x-tenant-id": tenant_id}
            )
            
            if response.status_code == 200:
                result = response.json()
                customer_id = result.get("customer_id")
                print(f"  ✅ Customer created: {customer_id}")
                self.test_data["customer_id"] = customer_id
                return customer_id
            else:
                print(f"  ❌ Customer creation failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Customer creation error: {str(e)}")
            return None
    
    async def test_payment_intent_creation(self) -> str:
        """Test payment intent creation"""
        print("\n💳 Testing payment intent creation...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for payment intent creation")
            return None
        
        payment_data = {
            "tenant_id": tenant_id,
            "amount_minor": 2500,  # £25.00
            "currency": "GBP",
            "provider": "stripe",
            "metadata": {
                "description": "Test payment intent",
                "customer_id": self.test_data.get("customer_id"),
                "test": True
            }
        }
        
        try:
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/intent",
                json=payment_data,
                headers={"x-tenant-id": tenant_id}
            )
            
            if response.status_code == 200:
                result = response.json()
                payment_intent_id = result.get("payment_intent_id")
                print(f"  ✅ Payment intent created: {payment_intent_id}")
                print(f"  📝 Client secret: {result.get('client_secret', 'N/A')}")
                self.test_data["payment_intent_id"] = payment_intent_id
                return payment_intent_id
            else:
                print(f"  ❌ Payment intent creation failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Payment intent creation error: {str(e)}")
            return None
    
    async def test_webhook_processing(self) -> bool:
        """Test webhook processing"""
        print("\n🔗 Testing webhook processing...")
        
        payment_intent_id = self.test_data.get("payment_intent_id")
        if not payment_intent_id:
            print("  ❌ No payment_intent_id available for webhook testing")
            return False
        
        # Simulate Stripe webhook payload
        webhook_payload = {
            "id": "evt_test_webhook",
            "object": "event",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": payment_intent_id,
                    "object": "payment_intent",
                    "amount": 2500,
                    "currency": "gbp",
                    "status": "succeeded",
                    "client_secret": "pi_test_secret"
                }
            }
        }
        
        try:
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/webhook/stripe",
                json=webhook_payload,
                headers={"stripe-signature": "test_signature"}
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Webhook processed successfully: {result}")
                return True
            else:
                print(f"  ❌ Webhook processing failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Webhook processing error: {str(e)}")
            return False
    
    async def test_payment_refund(self) -> bool:
        """Test payment refund"""
        print("\n💰 Testing payment refund...")
        
        tenant_id = self.test_data.get("tenant_id")
        payment_intent_id = self.test_data.get("payment_intent_id")
        
        if not tenant_id or not payment_intent_id:
            print("  ❌ Missing tenant_id or payment_intent_id for refund testing")
            return False
        
        refund_data = {
            "tenant_id": tenant_id,
            "payment_intent_id": payment_intent_id,
            "amount_minor": 1000,  # Partial refund of £10.00
            "reason": "Customer requested refund"
        }
        
        try:
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/refund",
                json=refund_data,
                headers={"x-tenant-id": tenant_id}
            )
            
            if response.status_code == 200:
                result = response.json()
                refund_id = result.get("refund_id")
                print(f"  ✅ Refund created: {refund_id}")
                print(f"  💵 Refund amount: £{result.get('amount_minor', 0) / 100:.2f}")
                return True
            else:
                print(f"  ❌ Refund creation failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Refund creation error: {str(e)}")
            return False
    
    async def test_transaction_listing(self) -> bool:
        """Test transaction listing and filtering"""
        print("\n📋 Testing transaction listing...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for transaction listing")
            return False
        
        try:
            # Test basic listing
            response = await self.client.get(
                f"{PAYMENTS_SERVICE}/payments/v2/transactions",
                params={"tenant_id": tenant_id, "limit": 10},
                headers={"x-tenant-id": tenant_id}
            )
            
            if response.status_code == 200:
                result = response.json()
                transactions = result.get("transactions", [])
                print(f"  ✅ Listed {len(transactions)} transactions")
                
                # Test filtering by provider
                response = await self.client.get(
                    f"{PAYMENTS_SERVICE}/payments/v2/transactions",
                    params={"tenant_id": tenant_id, "provider": "stripe", "limit": 5},
                    headers={"x-tenant-id": tenant_id}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"  ✅ Filtered to {len(result.get('transactions', []))} Stripe transactions")
                    return True
                else:
                    print(f"  ⚠️ Provider filtering failed: {response.status_code}")
                    return False
            else:
                print(f"  ❌ Transaction listing failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Transaction listing error: {str(e)}")
            return False
    
    async def test_payment_reports(self) -> bool:
        """Test payment reports and analytics"""
        print("\n📊 Testing payment reports...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for payment reports")
            return False
        
        # Test reports for the last 30 days
        end_date = datetime.now().date()
        start_date = end_date.replace(day=1)  # Start of current month
        
        try:
            response = await self.client.get(
                f"{PAYMENTS_SERVICE}/payments/v2/reports",
                params={
                    "tenant_id": tenant_id,
                    "period_start": start_date.isoformat(),
                    "period_end": end_date.isoformat(),
                    "currency": "GBP"
                },
                headers={"x-tenant-id": tenant_id}
            )
            
            if response.status_code == 200:
                result = response.json()
                summary = result.get("summary", {})
                daily_trends = result.get("daily_trends", [])
                
                print(f"  ✅ Payment reports generated")
                print(f"  📈 Summary: {len(summary)} providers")
                print(f"  📅 Daily trends: {len(daily_trends)} days")
                
                # Print summary details
                for provider, statuses in summary.items():
                    for status, data in statuses.items():
                        count = data.get("count", 0)
                        amount = data.get("total_amount_minor", 0)
                        print(f"    {provider} {status}: {count} payments, £{amount/100:.2f}")
                
                return True
            else:
                print(f"  ❌ Payment reports failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Payment reports error: {str(e)}")
            return False
    
    async def test_integration_endpoints(self) -> bool:
        """Test integration endpoints"""
        print("\n🔗 Testing integration endpoints...")
        
        tenant_id = self.test_data.get("tenant_id")
        if not tenant_id:
            print("  ❌ No tenant_id available for integration testing")
            return False
        
        # Test payment required integration
        integration_data = {
            "order_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "total_amount_minor": 3500,  # £35.00
            "currency": "GBP"
        }
        
        try:
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/integration/orders/payment-required",
                json=integration_data
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Payment required integration successful")
                print(f"  💳 Payment intent created: {result.get('result', {}).get('payment_intent_id', 'N/A')}")
                return True
            else:
                print(f"  ❌ Payment required integration failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Integration testing error: {str(e)}")
            return False
    
    async def test_legacy_endpoint_deprecation(self) -> bool:
        """Test legacy endpoint deprecation warnings"""
        print("\n⚠️ Testing legacy endpoint deprecation...")
        
        try:
            # Test deprecated Stripe endpoints
            deprecated_endpoints = [
                "/stripe/customers",
                "/stripe/payment-intent", 
                "/stripe/webhook"
            ]
            
            for endpoint in deprecated_endpoints:
                response = await self.client.post(f"{PAYMENTS_SERVICE}{endpoint}")
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("deprecated"):
                        print(f"  ✅ {endpoint}: Correctly marked as deprecated")
                        print(f"    → Migrate to: {result.get('migrate_to', 'N/A')}")
                    else:
                        print(f"  ❌ {endpoint}: Not marked as deprecated")
                        return False
                else:
                    print(f"  ❌ {endpoint}: Unexpected status {response.status_code}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"  ❌ Legacy endpoint testing error: {str(e)}")
            return False
    
    async def test_metrics_endpoint(self) -> bool:
        """Test Prometheus metrics endpoint"""
        print("\n📈 Testing metrics endpoint...")
        
        try:
            response = await self.client.get(f"{PAYMENTS_SERVICE}/metrics")
            
            if response.status_code == 200:
                metrics_data = response.text
                print(f"  ✅ Metrics endpoint accessible")
                print(f"  📊 Metrics data length: {len(metrics_data)} characters")
                
                # Check for expected metrics
                expected_metrics = [
                    "payment_requests_total",
                    "payment_amount_total", 
                    "payment_duration_seconds",
                    "webhook_requests_total",
                    "saga_duration_seconds"
                ]
                
                for metric in expected_metrics:
                    if metric in metrics_data:
                        print(f"    ✅ {metric}: Present")
                    else:
                        print(f"    ⚠️ {metric}: Missing")
                
                return True
            else:
                print(f"  ❌ Metrics endpoint failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Metrics endpoint error: {str(e)}")
            return False
    
    async def test_error_scenarios(self) -> bool:
        """Test error scenarios and edge cases"""
        print("\n🚨 Testing error scenarios...")
        
        try:
            # Test invalid tenant_id
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/intent",
                json={
                    "tenant_id": "invalid-uuid",
                    "amount_minor": 1000,
                    "currency": "GBP"
                }
            )
            
            if response.status_code in [400, 422]:
                print("  ✅ Invalid tenant_id properly rejected")
            else:
                print(f"  ❌ Invalid tenant_id not properly handled: {response.status_code}")
                return False
            
            # Test missing required fields
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/intent",
                json={
                    "tenant_id": str(uuid.uuid4()),
                    "currency": "GBP"
                    # Missing amount_minor
                }
            )
            
            if response.status_code in [400, 422]:
                print("  ✅ Missing required fields properly rejected")
            else:
                print(f"  ❌ Missing required fields not properly handled: {response.status_code}")
                return False
            
            # Test invalid currency
            response = await self.client.post(
                f"{PAYMENTS_SERVICE}/payments/v2/intent",
                json={
                    "tenant_id": str(uuid.uuid4()),
                    "amount_minor": 1000,
                    "currency": "INVALID"
                }
            )
            
            if response.status_code in [400, 422]:
                print("  ✅ Invalid currency properly rejected")
            else:
                print(f"  ❌ Invalid currency not properly handled: {response.status_code}")
                return False
            
            return True
            
        except Exception as e:
            print(f"  ❌ Error scenario testing failed: {str(e)}")
            return False
    
    async def run_comprehensive_test(self):
        """Run all payment service tests"""
        print("🚀 Starting Comprehensive Payments Service Tests")
        print("=" * 70)
        
        # Health check
        if not await self.health_check_payments_service():
            print("\n❌ Payments service is not healthy. Please start the service before running tests.")
            return False
        
        print("\n✅ Payments service is healthy. Proceeding with tests...")
        
        # Run all tests
        tests = [
            ("Provider Configuration", self.test_provider_configuration),
            ("Customer Creation", self.test_customer_creation),
            ("Payment Intent Creation", self.test_payment_intent_creation),
            ("Webhook Processing", self.test_webhook_processing),
            ("Payment Refund", self.test_payment_refund),
            ("Transaction Listing", self.test_transaction_listing),
            ("Payment Reports", self.test_payment_reports),
            ("Integration Endpoints", self.test_integration_endpoints),
            ("Legacy Endpoint Deprecation", self.test_legacy_endpoint_deprecation),
            ("Metrics Endpoint", self.test_metrics_endpoint),
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
        print("🎉 Payments Service Tests Completed!")
        print(f"📊 Results: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎯 All tests passed! Payments service is working correctly.")
        else:
            print("⚠️ Some tests failed. Please review the output above.")
        
        print(f"\n📝 Test data created:")
        print(f"   Tenant ID: {self.test_data.get('tenant_id', 'N/A')}")
        print(f"   Customer ID: {self.test_data.get('customer_id', 'N/A')}")
        print(f"   Payment Intent ID: {self.test_data.get('payment_intent_id', 'N/A')}")
        
        return passed_tests == total_tests

async def main():
    """Main test runner"""
    async with PaymentsServiceTester() as tester:
        success = await tester.run_comprehensive_test()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
