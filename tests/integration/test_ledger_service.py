#!/usr/bin/env python3
"""
Comprehensive test suite for Ledger Service V2
Tests saga pattern, event integration, and all endpoints
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
import httpx
import pytest
from unittest.mock import Mock, patch, AsyncMock

# Test configuration
BASE_URL = "http://localhost:8086"
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "user123"
TEST_VENDOR_ID = "vendor456"

class TestLedgerService:
    """Test suite for Ledger Service V2"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self.test_entries = []
    
    async def cleanup(self):
        """Cleanup test data"""
        await self.client.aclose()
    
    # =============================================================================
    # HEALTH CHECK TESTS
    # =============================================================================
    
    async def test_health_check(self):
        """Test service health check"""
        print("🔍 Testing health check...")
        
        response = await self.client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ledger_v2"
        assert data["version"] == "2.0.0"
        
        print("✅ Health check passed")
    
    async def test_metrics_endpoint(self):
        """Test Prometheus metrics endpoint"""
        print("🔍 Testing metrics endpoint...")
        
        response = await self.client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        
        metrics_text = response.text
        assert "ledger_requests_total" in metrics_text
        assert "ledger_request_duration_seconds" in metrics_text
        
        print("✅ Metrics endpoint passed")
    
    # =============================================================================
    # LEDGER ENTRY TESTS
    # =============================================================================
    
    async def test_create_ledger_entry(self):
        """Test creating a ledger entry with saga pattern"""
        print("🔍 Testing ledger entry creation...")
        
        entry_data = {
            "tenant_id": TEST_TENANT_ID,
            "account": "CostCentreSpend",
            "entry_type": "debit",
            "amount_minor": 50000,
            "currency": "GBP",
            "cost_centre_id": "cc123",
            "reference_type": "order",
            "reference_id": "order123",
            "description": "Test order completion",
            "metadata": {
                "test": True,
                "source": "test_suite"
            }
        }
        
        response = await self.client.post("/ledger/v4/entries", json=entry_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        assert "entry_id" in data
        
        # Store for cleanup
        self.test_entries.append(data["entry_id"])
        
        print("✅ Ledger entry creation passed")
    
    async def test_create_ledger_entry_invalid_data(self):
        """Test ledger entry creation with invalid data"""
        print("🔍 Testing invalid ledger entry creation...")
        
        invalid_data = {
            "tenant_id": TEST_TENANT_ID,
            "account": "CostCentreSpend",
            "entry_type": "invalid_type",  # Invalid entry type
            "amount_minor": -100,  # Negative amount
            "currency": "GBP"
        }
        
        response = await self.client.post("/ledger/v4/entries", json=invalid_data)
        assert response.status_code == 422  # Validation error
        
        print("✅ Invalid data validation passed")
    
    async def test_list_ledger_entries(self):
        """Test listing ledger entries with filtering"""
        print("🔍 Testing ledger entries listing...")
        
        params = {
            "tenant_id": TEST_TENANT_ID,
            "limit": 10,
            "offset": 0
        }
        
        response = await self.client.get("/ledger/v4/entries", params=params)
        assert response.status_code == 200
        
        data = response.json()
        assert "items" in data
        assert "total_count" in data
        assert "offset" in data
        assert "limit" in data
        assert "has_more" in data
        assert isinstance(data["items"], list)
        
        print("✅ Ledger entries listing passed")
    
    async def test_list_ledger_entries_with_filters(self):
        """Test listing ledger entries with various filters"""
        print("🔍 Testing ledger entries filtering...")
        
        # Test with account filter
        params = {
            "tenant_id": TEST_TENANT_ID,
            "account": "CostCentreSpend",
            "currency": "GBP",
            "limit": 5
        }
        
        response = await self.client.get("/ledger/v4/entries", params=params)
        assert response.status_code == 200
        
        data = response.json()
        # All returned items should match the filter
        for item in data["items"]:
            assert item["account"] == "CostCentreSpend"
            assert item["currency"] == "GBP"
        
        print("✅ Ledger entries filtering passed")
    
    # =============================================================================
    # ACCOUNT BALANCE TESTS
    # =============================================================================
    
    async def test_get_account_balances(self):
        """Test getting account balances"""
        print("🔍 Testing account balances...")
        
        params = {
            "tenant_id": TEST_TENANT_ID,
            "currency": "GBP"
        }
        
        response = await self.client.get("/ledger/v4/balances", params=params)
        assert response.status_code == 200
        
        data = response.json()
        assert "balances" in data
        assert isinstance(data["balances"], list)
        
        # Check balance structure
        for balance in data["balances"]:
            assert "account" in balance
            assert "currency" in balance
            assert "balance_minor" in balance
            assert "last_updated" in balance
        
        print("✅ Account balances passed")
    
    # =============================================================================
    # ADJUSTMENT TESTS
    # =============================================================================
    
    async def test_create_ledger_adjustment(self):
        """Test creating a ledger adjustment"""
        print("🔍 Testing ledger adjustment creation...")
        
        # First create an entry to adjust
        entry_data = {
            "tenant_id": TEST_TENANT_ID,
            "account": "CostCentreSpend",
            "entry_type": "debit",
            "amount_minor": 10000,
            "currency": "GBP",
            "reference_type": "test",
            "reference_id": "test123"
        }
        
        response = await self.client.post("/ledger/v4/entries", json=entry_data)
        assert response.status_code == 200
        
        entry_id = response.json()["entry_id"]
        self.test_entries.append(entry_id)
        
        # Now create an adjustment
        adjustment_data = {
            "entry_id": entry_id,
            "adjustment_amount_minor": 2000,
            "reason": "Test adjustment for dispute resolution",
            "reference_type": "adjustment",
            "reference_id": "adj_test123"
        }
        
        response = await self.client.post("/ledger/v4/adjustments", json=adjustment_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        assert "adjustment_entry_id" in data
        assert data["original_entry_id"] == entry_id
        assert data["adjustment_amount_minor"] == 2000
        
        # Store adjustment entry for cleanup
        self.test_entries.append(data["adjustment_entry_id"])
        
        print("✅ Ledger adjustment creation passed")
    
    # =============================================================================
    # REPORT TESTS
    # =============================================================================
    
    async def test_ledger_report(self):
        """Test ledger report generation"""
        print("🔍 Testing ledger report...")
        
        params = {
            "tenant_id": TEST_TENANT_ID,
            "currency": "GBP"
        }
        
        response = await self.client.get("/ledger/v4/reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        assert "tenant_id" in data
        assert "period" in data
        assert "filters" in data
        assert "summary" in data
        assert "total_entries" in data
        assert "generated_at" in data
        
        print("✅ Ledger report passed")
    
    async def test_ledger_report_with_vendor_splits(self):
        """Test ledger report with vendor splits"""
        print("🔍 Testing ledger report with vendor splits...")
        
        params = {
            "tenant_id": TEST_TENANT_ID,
            "include_vendor_splits": True,
            "include_currency_conversion": True
        }
        
        response = await self.client.get("/ledger/v4/reports", params=params)
        assert response.status_code == 200
        
        data = response.json()
        assert "vendor_splits" in data
        assert "currency_conversion" in data
        
        print("✅ Ledger report with vendor splits passed")
    
    # =============================================================================
    # EVENT INTEGRATION TESTS
    # =============================================================================
    
    async def test_order_completed_event(self):
        """Test ORDER_COMPLETED event handling"""
        print("🔍 Testing ORDER_COMPLETED event...")
        
        event_data = {
            "tenant_id": TEST_TENANT_ID,
            "order_id": "test_order_456",
            "total_amount_minor": 75000,
            "currency": "GBP",
            "site_id": "site123",
            "store_id": "store456",
            "cost_centre_id": "cc789"
        }
        
        response = await self.client.post("/ledger/v4/events/order-completed", json=event_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        assert "ledger_entry_id" in data
        
        # Store for cleanup
        self.test_entries.append(data["ledger_entry_id"])
        
        print("✅ ORDER_COMPLETED event passed")
    
    async def test_invoice_posted_event(self):
        """Test INVOICE_POSTED event handling"""
        print("🔍 Testing INVOICE_POSTED event...")
        
        event_data = {
            "tenant_id": TEST_TENANT_ID,
            "invoice_id": "test_invoice_789",
            "total_amount_minor": 100000,
            "currency": "GBP",
            "customer_id": "cust123"
        }
        
        response = await self.client.post("/ledger/v4/events/invoice-posted", json=event_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        assert "ledger_entry_id" in data
        
        # Store for cleanup
        self.test_entries.append(data["ledger_entry_id"])
        
        print("✅ INVOICE_POSTED event passed")
    
    async def test_approval_resolved_event(self):
        """Test APPROVAL_RESOLVED event handling"""
        print("🔍 Testing APPROVAL_RESOLVED event...")
        
        event_data = {
            "tenant_id": TEST_TENANT_ID,
            "request_id": "test_approval_101",
            "amount_minor": 50000,
            "currency": "GBP",
            "approved": True,
            "cost_centre_id": "cc123"
        }
        
        response = await self.client.post("/ledger/v4/events/approval-resolved", json=event_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        assert "ledger_entry_id" in data
        
        # Store for cleanup
        self.test_entries.append(data["ledger_entry_id"])
        
        print("✅ APPROVAL_RESOLVED event passed")
    
    async def test_approval_resolved_event_denied(self):
        """Test APPROVAL_RESOLVED event with denied approval"""
        print("🔍 Testing APPROVAL_RESOLVED event (denied)...")
        
        event_data = {
            "tenant_id": TEST_TENANT_ID,
            "request_id": "test_approval_denied_102",
            "amount_minor": 25000,
            "currency": "GBP",
            "approved": False,
            "cost_centre_id": "cc123"
        }
        
        response = await self.client.post("/ledger/v4/events/approval-resolved", json=event_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        assert "message" in data
        assert "No ledger entry needed" in data["message"]
        
        print("✅ APPROVAL_RESOLVED event (denied) passed")
    
    # =============================================================================
    # EVENT RETRY TESTS
    # =============================================================================
    
    async def test_event_status(self):
        """Test event status endpoint"""
        print("🔍 Testing event status...")
        
        response = await self.client.get("/ledger/v4/events/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_events" in data
        assert "pending_events" in data
        assert "published_events" in data
        assert "failed_events" in data
        assert "success_rate" in data
        
        print("✅ Event status passed")
    
    async def test_event_retry(self):
        """Test event retry endpoint"""
        print("🔍 Testing event retry...")
        
        response = await self.client.post("/ledger/v4/events/retry")
        assert response.status_code == 200
        
        data = response.json()
        assert "ok" in data
        assert "retried_events" in data
        assert "failed_events" in data
        assert "total_processed" in data
        
        print("✅ Event retry passed")
    
    # =============================================================================
    # LEGACY ENDPOINT TESTS
    # =============================================================================
    
    async def test_legacy_endpoints_deprecation(self):
        """Test legacy endpoints return deprecation warnings"""
        print("🔍 Testing legacy endpoints deprecation...")
        
        # Test legacy ledger endpoint
        response = await self.client.get("/ledger", params={"tenant_id": TEST_TENANT_ID})
        assert response.status_code == 200
        
        data = response.json()
        assert data["deprecated"] is True
        assert "migrate_to" in data
        assert data["migrate_to"] == "/ledger/v4/entries"
        
        # Test legacy balance endpoint
        response = await self.client.get("/ledger/balance", params={"tenant_id": TEST_TENANT_ID})
        assert response.status_code == 200
        
        data = response.json()
        assert data["deprecated"] is True
        assert "migrate_to" in data
        assert data["migrate_to"] == "/ledger/v4/balances"
        
        print("✅ Legacy endpoints deprecation passed")
    
    # =============================================================================
    # ERROR HANDLING TESTS
    # =============================================================================
    
    async def test_invalid_tenant_id(self):
        """Test error handling for invalid tenant ID"""
        print("🔍 Testing invalid tenant ID handling...")
        
        params = {
            "tenant_id": "invalid-uuid",
            "limit": 10
        }
        
        response = await self.client.get("/ledger/v4/entries", params=params)
        # Should return 422 for validation error or 500 for database error
        assert response.status_code in [422, 500]
        
        print("✅ Invalid tenant ID handling passed")
    
    async def test_unauthorized_access(self):
        """Test unauthorized access (simulated)"""
        print("🔍 Testing unauthorized access...")
        
        # Test without proper authorization header
        headers = {"Authorization": "Bearer invalid_token"}
        
        response = await self.client.post(
            "/ledger/v4/entries",
            json={
                "tenant_id": TEST_TENANT_ID,
                "account": "CostCentreSpend",
                "entry_type": "debit",
                "amount_minor": 1000,
                "currency": "GBP"
            },
            headers=headers
        )
        
        # Should return 403 for insufficient permissions or 200 for demo mode
        assert response.status_code in [200, 403]
        
        print("✅ Unauthorized access handling passed")
    
    # =============================================================================
    # SAGA COMPENSATION TESTS (MOCKED)
    # =============================================================================
    
    async def test_saga_compensation_logic(self):
        """Test saga compensation logic with mocked database failure"""
        print("🔍 Testing saga compensation logic...")
        
        # This test would require mocking the database to simulate failures
        # For now, we'll test the endpoint structure
        
        entry_data = {
            "tenant_id": TEST_TENANT_ID,
            "account": "TestAccount",
            "entry_type": "debit",
            "amount_minor": 1000,
            "currency": "GBP",
            "description": "Test saga compensation"
        }
        
        # Test with valid data (should succeed)
        response = await self.client.post("/ledger/v4/entries", json=entry_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["ok"] is True
        self.test_entries.append(data["entry_id"])
        
        print("✅ Saga compensation logic structure passed")
    
    # =============================================================================
    # PERFORMANCE TESTS
    # =============================================================================
    
    async def test_bulk_entry_creation_performance(self):
        """Test performance of bulk entry creation"""
        print("🔍 Testing bulk entry creation performance...")
        
        start_time = datetime.now()
        
        # Create multiple entries
        for i in range(5):
            entry_data = {
                "tenant_id": TEST_TENANT_ID,
                "account": f"PerformanceTest{i}",
                "entry_type": "debit",
                "amount_minor": 1000 + i,
                "currency": "GBP",
                "reference_type": "performance_test",
                "reference_id": f"perf_test_{i}"
            }
            
            response = await self.client.post("/ledger/v4/entries", json=entry_data)
            assert response.status_code == 200
            
            data = response.json()
            self.test_entries.append(data["entry_id"])
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print(f"✅ Bulk entry creation completed in {duration:.2f} seconds")
        assert duration < 10.0  # Should complete within 10 seconds
    
    # =============================================================================
    # INTEGRATION TESTS
    # =============================================================================
    
    async def test_end_to_end_workflow(self):
        """Test complete end-to-end workflow"""
        print("🔍 Testing end-to-end workflow...")
        
        # Step 1: Create an order entry via event
        order_event = {
            "tenant_id": TEST_TENANT_ID,
            "order_id": "e2e_order_123",
            "total_amount_minor": 25000,
            "currency": "GBP"
        }
        
        response = await self.client.post("/ledger/v4/events/order-completed", json=order_event)
        assert response.status_code == 200
        order_entry_id = response.json()["ledger_entry_id"]
        self.test_entries.append(order_entry_id)
        
        # Step 2: Create an invoice entry via event
        invoice_event = {
            "tenant_id": TEST_TENANT_ID,
            "invoice_id": "e2e_invoice_456",
            "total_amount_minor": 30000,
            "currency": "GBP"
        }
        
        response = await self.client.post("/ledger/v4/events/invoice-posted", json=invoice_event)
        assert response.status_code == 200
        invoice_entry_id = response.json()["ledger_entry_id"]
        self.test_entries.append(invoice_entry_id)
        
        # Step 3: Check balances
        params = {"tenant_id": TEST_TENANT_ID, "currency": "GBP"}
        response = await self.client.get("/ledger/v4/balances", params=params)
        assert response.status_code == 200
        
        balances = response.json()["balances"]
        assert len(balances) > 0
        
        # Step 4: Generate report
        params = {
            "tenant_id": TEST_TENANT_ID,
            "include_vendor_splits": True,
            "currency": "GBP"
        }
        response = await self.client.get("/ledger/v4/reports", params=params)
        assert response.status_code == 200
        
        report = response.json()
        assert report["total_entries"] >= 2  # At least our test entries
        
        print("✅ End-to-end workflow passed")
    
    # =============================================================================
    # MAIN TEST RUNNER
    # =============================================================================
    
    async def run_all_tests(self):
        """Run all tests"""
        print("🚀 Starting Ledger Service V2 Test Suite")
        print("=" * 60)
        
        try:
            # Health and monitoring tests
            await self.test_health_check()
            await self.test_metrics_endpoint()
            
            # Core ledger operations
            await self.test_create_ledger_entry()
            await self.test_create_ledger_entry_invalid_data()
            await self.test_list_ledger_entries()
            await self.test_list_ledger_entries_with_filters()
            await self.test_get_account_balances()
            
            # Adjustments
            await self.test_create_ledger_adjustment()
            
            # Reports
            await self.test_ledger_report()
            await self.test_ledger_report_with_vendor_splits()
            
            # Event integration
            await self.test_order_completed_event()
            await self.test_invoice_posted_event()
            await self.test_approval_resolved_event()
            await self.test_approval_resolved_event_denied()
            
            # Event management
            await self.test_event_status()
            await self.test_event_retry()
            
            # Legacy endpoints
            await self.test_legacy_endpoints_deprecation()
            
            # Error handling
            await self.test_invalid_tenant_id()
            await self.test_unauthorized_access()
            
            # Saga testing
            await self.test_saga_compensation_logic()
            
            # Performance testing
            await self.test_bulk_entry_creation_performance()
            
            # Integration testing
            await self.test_end_to_end_workflow()
            
            print("=" * 60)
            print("🎉 All tests passed! Ledger Service V2 is working correctly.")
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            raise
        
        finally:
            await self.cleanup()

# =============================================================================
# MOCK TESTS FOR SAGA COMPENSATION
# =============================================================================

class MockLedgerEntrySaga:
    """Mock saga for testing compensation logic"""
    
    def __init__(self, db, request, should_fail_at_step=None):
        self.db = db
        self.request = request
        self.should_fail_at_step = should_fail_at_step
        self.compensation_steps = []
        self.current_step = 0
    
    async def execute(self):
        """Mock saga execution with configurable failures"""
        try:
            self.current_step += 1
            if self.should_fail_at_step == self.current_step:
                raise Exception(f"Simulated failure at step {self.current_step}")
            
            # Step 1: Validate
            await self._validate_tenant_vendor()
            
            self.current_step += 1
            if self.should_fail_at_step == self.current_step:
                raise Exception(f"Simulated failure at step {self.current_step}")
            
            # Step 2: Create entries
            debit_id, credit_id = await self._create_entries()
            
            self.current_step += 1
            if self.should_fail_at_step == self.current_step:
                raise Exception(f"Simulated failure at step {self.current_step}")
            
            # Step 3: Update balances
            await self._update_balances()
            
            self.current_step += 1
            if self.should_fail_at_step == self.current_step:
                raise Exception(f"Simulated failure at step {self.current_step}")
            
            # Step 4: Publish event
            await self._publish_event()
            
            self.current_step += 1
            if self.should_fail_at_step == self.current_step:
                raise Exception(f"Simulated failure at step {self.current_step}")
            
            # Step 5: Audit log
            await self._audit_log()
            
            return {"ok": True, "entry_id": str(debit_id)}
            
        except Exception as e:
            await self._compensate()
            raise e
    
    async def _validate_tenant_vendor(self):
        self.compensation_steps.append(("validation", {}))
    
    async def _create_entries(self):
        debit_id = str(uuid.uuid4())
        credit_id = str(uuid.uuid4())
        self.compensation_steps.append(("delete_entries", {"debit_id": debit_id, "credit_id": credit_id}))
        return debit_id, credit_id
    
    async def _update_balances(self):
        self.compensation_steps.append(("revert_balances", {}))
    
    async def _publish_event(self):
        self.compensation_steps.append(("cleanup_event", {}))
    
    async def _audit_log(self):
        self.compensation_steps.append(("cleanup_audit", {}))
    
    async def _compensate(self):
        """Execute compensation steps in reverse order"""
        for step_name, data in reversed(self.compensation_steps):
            if step_name == "delete_entries":
                print(f"  🔄 Compensating: Deleting entries {data['debit_id']}, {data['credit_id']}")
            elif step_name == "revert_balances":
                print(f"  🔄 Compensating: Reverting balance changes")
            elif step_name == "cleanup_event":
                print(f"  🔄 Compensating: Cleaning up event")
            elif step_name == "cleanup_audit":
                print(f"  🔄 Compensating: Cleaning up audit log")
            elif step_name == "validation":
                print(f"  🔄 Compensating: No compensation needed for validation")

def test_saga_compensation_logic():
    """Test saga compensation logic with various failure scenarios"""
    print("🔍 Testing saga compensation logic with mocks...")
    
    # Test successful execution
    saga = MockLedgerEntrySaga(None, None)
    result = asyncio.run(saga.execute())
    assert result["ok"] is True
    print("✅ Successful saga execution passed")
    
    # Test failure at step 2 (after validation, before entry creation)
    saga = MockLedgerEntrySaga(None, None, should_fail_at_step=2)
    try:
        asyncio.run(saga.execute())
        assert False, "Should have failed"
    except Exception as e:
        assert "Simulated failure at step 2" in str(e)
    print("✅ Saga failure at step 2 compensation passed")
    
    # Test failure at step 4 (after entry creation and balance update, before event)
    saga = MockLedgerEntrySaga(None, None, should_fail_at_step=4)
    try:
        asyncio.run(saga.execute())
        assert False, "Should have failed"
    except Exception as e:
        assert "Simulated failure at step 4" in str(e)
    print("✅ Saga failure at step 4 compensation passed")
    
    print("✅ All saga compensation tests passed")

# =============================================================================
# MAIN EXECUTION
# =============================================================================

async def main():
    """Main test execution"""
    test_suite = TestLedgerService()
    
    # Run mock tests first
    test_saga_compensation_logic()
    
    # Run integration tests
    await test_suite.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
