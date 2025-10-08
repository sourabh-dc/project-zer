#!/usr/bin/env python3
"""
Comprehensive Integration Test Script for ZeroQue V2 Architecture
Tests all service integrations and event flows
"""

import asyncio
import httpx
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List
import sys

# Service URLs
SERVICES = {
    "catalog": "http://localhost:8080",
    "orders": "http://localhost:8081", 
    "provisioning": "http://localhost:8082",
    "billing": "http://localhost:8083",
    "approvals": "http://localhost:8084",
    "pricing": "http://localhost:8085",
    "ledger": "http://localhost:8086",
    "cv_connector": "http://localhost:8100",
    "cv_gateway": "http://localhost:8101"
}

class IntegrationTester:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.test_results = {}
        self.test_data = {}
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def health_check_all_services(self) -> Dict[str, bool]:
        """Check health of all services"""
        print("🔍 Checking health of all services...")
        health_status = {}
        
        for service_name, url in SERVICES.items():
            try:
                response = await self.client.get(f"{url}/health")
                health_status[service_name] = response.status_code == 200
                status = "✅ Healthy" if health_status[service_name] else "❌ Unhealthy"
                print(f"  {service_name}: {status}")
            except Exception as e:
                health_status[service_name] = False
                print(f"  {service_name}: ❌ Unreachable ({str(e)})")
        
        return health_status
    
    async def test_tenant_creation_flow(self) -> str:
        """Test tenant creation and CV configuration setup"""
        print("\n🏢 Testing tenant creation flow...")
        
        tenant_id = str(uuid.uuid4())
        
        # Create tenant in provisioning service
        tenant_data = {
            "tenant_id": tenant_id,
            "name": f"Test Tenant {datetime.now().strftime('%H%M%S')}",
            "status": "active",
            "settings": {"currency": "GBP", "timezone": "UTC"}
        }
        
        try:
            response = await self.client.post(
                f"{SERVICES['provisioning']}/provisioning/v2/tenants",
                json=tenant_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ Tenant created: {tenant_id}")
                
                # Test CV Connector integration for tenant creation
                cv_response = await self.client.post(
                    f"{SERVICES['cv_connector']}/cv/v4/integration/provisioning/tenant-created",
                    json={"tenant_id": tenant_id}
                )
                
                if cv_response.status_code == 200:
                    print(f"  ✅ CV configuration set up for tenant")
                else:
                    print(f"  ⚠️ CV configuration setup failed: {cv_response.status_code}")
                
                self.test_data["tenant_id"] = tenant_id
                return tenant_id
            else:
                print(f"  ❌ Tenant creation failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Tenant creation error: {str(e)}")
            return None
    
    async def test_user_creation_flow(self, tenant_id: str) -> str:
        """Test user creation and CV sync"""
        print("\n👤 Testing user creation flow...")
        
        user_id = str(uuid.uuid4())
        
        user_data = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": f"testuser_{datetime.now().strftime('%H%M%S')}@example.com",
            "name": "Test User",
            "status": "active"
        }
        
        try:
            response = await self.client.post(
                f"{SERVICES['provisioning']}/provisioning/v2/users",
                json=user_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ User created: {user_id}")
                
                # Test CV Connector integration for user creation
                cv_response = await self.client.post(
                    f"{SERVICES['cv_connector']}/cv/v4/integration/provisioning/user-created",
                    json={"tenant_id": tenant_id, "user": user_data}
                )
                
                if cv_response.status_code == 200:
                    print(f"  ✅ User synced to CV provider")
                else:
                    print(f"  ⚠️ User sync failed: {cv_response.status_code}")
                
                self.test_data["user_id"] = user_id
                return user_id
            else:
                print(f"  ❌ User creation failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ User creation error: {str(e)}")
            return None
    
    async def test_product_creation_flow(self, tenant_id: str) -> str:
        """Test product creation and CV sync"""
        print("\n📦 Testing product creation flow...")
        
        product_id = str(uuid.uuid4())
        
        product_data = {
            "product_id": product_id,
            "tenant_id": tenant_id,
            "name": f"Test Product {datetime.now().strftime('%H%M%S')}",
            "sku": f"TEST-{datetime.now().strftime('%H%M%S')}",
            "price_minor": 1000,  # £10.00
            "currency": "GBP",
            "status": "active"
        }
        
        try:
            response = await self.client.post(
                f"{SERVICES['catalog']}/catalog/v2/products",
                json=product_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ Product created: {product_id}")
                
                # Test CV Connector integration for product creation
                cv_response = await self.client.post(
                    f"{SERVICES['cv_connector']}/cv/v4/integration/catalog/product-created",
                    json={"tenant_id": tenant_id, "product": product_data}
                )
                
                if cv_response.status_code == 200:
                    print(f"  ✅ Product synced to CV provider")
                else:
                    print(f"  ⚠️ Product sync failed: {cv_response.status_code}")
                
                self.test_data["product_id"] = product_id
                return product_id
            else:
                print(f"  ❌ Product creation failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Product creation error: {str(e)}")
            return None
    
    async def test_order_creation_flow(self, tenant_id: str, user_id: str, product_id: str) -> str:
        """Test order creation and integrations"""
        print("\n🛒 Testing order creation flow...")
        
        order_id = str(uuid.uuid4())
        
        order_data = {
            "order_id": order_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "currency": "GBP",
            "total_minor": 1000,
            "items": [{
                "product_id": product_id,
                "quantity": 1,
                "price_minor": 1000,
                "total_minor": 1000
            }],
            "status": "pending"
        }
        
        try:
            response = await self.client.post(
                f"{SERVICES['orders']}/orders/v2",
                json=order_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ Order created: {order_id}")
                
                # Test CV Gateway integration for order creation
                cv_response = await self.client.post(
                    f"{SERVICES['cv_gateway']}/cv/v4/integration/orders/create-order",
                    json={"tenant_id": tenant_id, "order_data": order_data}
                )
                
                if cv_response.status_code == 200:
                    print(f"  ✅ Order sent to CV Gateway")
                else:
                    print(f"  ⚠️ CV Gateway order creation failed: {cv_response.status_code}")
                
                # Test budget check with Approvals service
                budget_response = await self.client.post(
                    f"{SERVICES['cv_gateway']}/cv/v4/integration/approvals/budget-check",
                    json={
                        "tenant_id": tenant_id,
                        "amount_minor": 1000,
                        "currency": "GBP"
                    }
                )
                
                if budget_response.status_code == 200:
                    print(f"  ✅ Budget check completed")
                else:
                    print(f"  ⚠️ Budget check failed: {budget_response.status_code}")
                
                self.test_data["order_id"] = order_id
                return order_id
            else:
                print(f"  ❌ Order creation failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Order creation error: {str(e)}")
            return None
    
    async def test_order_completion_flow(self, tenant_id: str, order_id: str):
        """Test order completion and ledger integration"""
        print("\n✅ Testing order completion flow...")
        
        try:
            # Complete the order
            completion_data = {
                "order_id": order_id,
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat()
            }
            
            response = await self.client.put(
                f"{SERVICES['orders']}/orders/v2/{order_id}/complete",
                json=completion_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ Order completed: {order_id}")
                
                # Test Orders -> Ledger integration
                ledger_response = await self.client.post(
                    f"{SERVICES['orders']}/orders/v2/integration/ledger/order-completed",
                    json={
                        "order_id": order_id,
                        "tenant_id": tenant_id,
                        "total_amount_minor": 1000,
                        "currency": "GBP"
                    }
                )
                
                if ledger_response.status_code == 200:
                    print(f"  ✅ Ledger entries created for order")
                else:
                    print(f"  ⚠️ Ledger integration failed: {ledger_response.status_code}")
                
                # Test Ledger service directly
                ledger_direct_response = await self.client.post(
                    f"{SERVICES['ledger']}/ledger/v4/integration/orders/order-completed",
                    json={
                        "order_id": order_id,
                        "tenant_id": tenant_id,
                        "total_amount_minor": 1000,
                        "currency": "GBP"
                    }
                )
                
                if ledger_direct_response.status_code == 200:
                    print(f"  ✅ Direct ledger integration successful")
                else:
                    print(f"  ⚠️ Direct ledger integration failed: {ledger_direct_response.status_code}")
                
            else:
                print(f"  ❌ Order completion failed: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ Order completion error: {str(e)}")
    
    async def test_approval_flow(self, tenant_id: str):
        """Test approval creation and resolution"""
        print("\n🔐 Testing approval flow...")
        
        approval_id = str(uuid.uuid4())
        
        approval_data = {
            "approval_id": approval_id,
            "tenant_id": tenant_id,
            "amount_minor": 1000,
            "currency": "GBP",
            "reason": "Test approval for integration",
            "status": "pending"
        }
        
        try:
            # Create approval request
            response = await self.client.post(
                f"{SERVICES['approvals']}/approvals/v2/requests",
                json=approval_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ Approval request created: {approval_id}")
                
                # Approve the request
                approval_response = await self.client.post(
                    f"{SERVICES['approvals']}/approvals/v2/requests/{approval_id}/approve",
                    json={"approved_by": "test_user", "notes": "Integration test approval"}
                )
                
                if approval_response.status_code == 200:
                    print(f"  ✅ Approval granted: {approval_id}")
                    
                    # Test Approvals -> Ledger integration
                    ledger_response = await self.client.post(
                        f"{SERVICES['approvals']}/approvals/v2/integration/ledger/approval-resolved",
                        json={
                            "approval_id": approval_id,
                            "tenant_id": tenant_id,
                            "amount_minor": 1000,
                            "currency": "GBP",
                            "status": "approved"
                        }
                    )
                    
                    if ledger_response.status_code == 200:
                        print(f"  ✅ Ledger entries created for approval")
                    else:
                        print(f"  ⚠️ Approval ledger integration failed: {ledger_response.status_code}")
                    
                else:
                    print(f"  ❌ Approval failed: {approval_response.status_code}")
            else:
                print(f"  ❌ Approval request creation failed: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ Approval flow error: {str(e)}")
    
    async def test_billing_flow(self, tenant_id: str, order_id: str):
        """Test invoice creation and billing integration"""
        print("\n💰 Testing billing flow...")
        
        invoice_id = str(uuid.uuid4())
        
        invoice_data = {
            "invoice_id": invoice_id,
            "tenant_id": tenant_id,
            "order_id": order_id,
            "total_amount_minor": 1000,
            "currency": "GBP",
            "status": "draft"
        }
        
        try:
            # Create invoice
            response = await self.client.post(
                f"{SERVICES['billing']}/billing/v2/invoices",
                json=invoice_data
            )
            
            if response.status_code == 200:
                print(f"  ✅ Invoice created: {invoice_id}")
                
                # Test CV Gateway integration for invoice creation
                cv_response = await self.client.post(
                    f"{SERVICES['cv_gateway']}/cv/v4/integration/billing/create-invoice",
                    json={
                        "tenant_id": tenant_id,
                        "order_id": order_id,
                        "total_amount_minor": 1000,
                        "currency": "GBP",
                        "items": [{"product_id": "test", "quantity": 1, "price_minor": 1000}]
                    }
                )
                
                if cv_response.status_code == 200:
                    print(f"  ✅ Invoice creation via CV Gateway")
                else:
                    print(f"  ⚠️ CV Gateway invoice creation failed: {cv_response.status_code}")
                
                # Post the invoice
                post_response = await self.client.put(
                    f"{SERVICES['billing']}/billing/v2/invoices/{invoice_id}/post"
                )
                
                if post_response.status_code == 200:
                    print(f"  ✅ Invoice posted: {invoice_id}")
                    
                    # Test Billing -> Ledger integration
                    ledger_response = await self.client.post(
                        f"{SERVICES['billing']}/billing/v2/integration/ledger/invoice-posted",
                        json={
                            "invoice_id": invoice_id,
                            "tenant_id": tenant_id,
                            "total_amount_minor": 1000,
                            "currency": "GBP"
                        }
                    )
                    
                    if ledger_response.status_code == 200:
                        print(f"  ✅ Ledger entries created for invoice")
                    else:
                        print(f"  ⚠️ Invoice ledger integration failed: {ledger_response.status_code}")
                    
                else:
                    print(f"  ❌ Invoice posting failed: {post_response.status_code}")
            else:
                print(f"  ❌ Invoice creation failed: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ Billing flow error: {str(e)}")
    
    async def test_integration_status(self):
        """Test integration status endpoints"""
        print("\n📊 Testing integration status endpoints...")
        
        for service_name, url in SERVICES.items():
            try:
                response = await self.client.get(f"{url}/integration/status")
                if response.status_code == 200:
                    status_data = response.json()
                    print(f"  ✅ {service_name}: Integration status available")
                else:
                    print(f"  ⚠️ {service_name}: Integration status failed ({response.status_code})")
            except Exception as e:
                print(f"  ❌ {service_name}: Integration status error ({str(e)})")
    
    async def run_comprehensive_test(self):
        """Run all integration tests"""
        print("🚀 Starting Comprehensive Integration Tests")
        print("=" * 60)
        
        # Health check
        health_status = await self.health_check_all_services()
        
        if not all(health_status.values()):
            print("\n❌ Some services are not healthy. Please start all services before running tests.")
            return False
        
        print("\n✅ All services are healthy. Proceeding with integration tests...")
        
        # Test tenant creation
        tenant_id = await self.test_tenant_creation_flow()
        if not tenant_id:
            print("\n❌ Tenant creation failed. Cannot proceed with other tests.")
            return False
        
        # Test user creation
        user_id = await self.test_user_creation_flow(tenant_id)
        if not user_id:
            print("\n❌ User creation failed. Cannot proceed with other tests.")
            return False
        
        # Test product creation
        product_id = await self.test_product_creation_flow(tenant_id)
        if not product_id:
            print("\n❌ Product creation failed. Cannot proceed with other tests.")
            return False
        
        # Test order creation
        order_id = await self.test_order_creation_flow(tenant_id, user_id, product_id)
        if not order_id:
            print("\n❌ Order creation failed. Cannot proceed with other tests.")
            return False
        
        # Test order completion
        await self.test_order_completion_flow(tenant_id, order_id)
        
        # Test approval flow
        await self.test_approval_flow(tenant_id)
        
        # Test billing flow
        await self.test_billing_flow(tenant_id, order_id)
        
        # Test integration status
        await self.test_integration_status()
        
        print("\n" + "=" * 60)
        print("🎉 Integration tests completed!")
        print(f"📝 Test data created:")
        print(f"   Tenant ID: {self.test_data.get('tenant_id', 'N/A')}")
        print(f"   User ID: {self.test_data.get('user_id', 'N/A')}")
        print(f"   Product ID: {self.test_data.get('product_id', 'N/A')}")
        print(f"   Order ID: {self.test_data.get('order_id', 'N/A')}")
        
        return True

async def main():
    """Main test runner"""
    async with IntegrationTester() as tester:
        success = await tester.run_comprehensive_test()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
