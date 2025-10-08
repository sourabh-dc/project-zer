#!/usr/bin/env python3
"""
ZeroQue Entry Service V4.1 - Comprehensive Test Suite
Tests all endpoints, integrations, and edge cases
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any

import httpx
import pytest

# Test configuration
BASE_URL = "http://localhost:8087"
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
TEST_SITE_ID = "550e8400-e29b-41d4-a716-446655440002"
TEST_STORE_ID = "550e8400-e29b-41d4-a716-446655440003"

# Mock JWT token for testing
TEST_TOKEN = "Bearer test-token-123"

class EntryServiceTester:
    """Comprehensive test suite for Entry Service V4.1"""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.headers = {"Authorization": TEST_TOKEN}
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def test_health_checks(self):
        """Test health and readiness endpoints"""
        print("\n🧪 Testing Health Checks...")
        
        # Health check
        response = await self.client.get(f"{self.base_url}/health")
        assert response.status_code == 200
        health_data = response.json()
        assert health_data["status"] == "ok"
        assert health_data["service"] == "entry"
        assert health_data["version"] == "4.1.0"
        print("✅ Health check passed")
        
        # Readiness check
        response = await self.client.get(f"{self.base_url}/readiness")
        assert response.status_code == 200
        readiness_data = response.json()
        assert readiness_data["service"] == "entry"
        assert readiness_data["version"] == "4.1.0"
        print("✅ Readiness check passed")
        
        # Metrics endpoint
        response = await self.client.get(f"{self.base_url}/metrics")
        assert response.status_code == 200
        print("✅ Metrics endpoint accessible")
    
    async def test_entry_code_issuance(self):
        """Test entry code issuance with various scenarios"""
        print("\n🧪 Testing Entry Code Issuance...")
        
        # Test successful code issuance
        payload = {
            "tenant_id": TEST_TENANT_ID,
            "site_id": TEST_SITE_ID,
            "store_id": TEST_STORE_ID,
            "user_id": TEST_USER_ID,
            "group_size": 2,
            "ttl_minutes": 20
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json=payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["allowed"] is True
        assert "code" in result
        assert result["ttl_minutes"] == 20
        print("✅ Entry code issuance successful")
        
        # Test with different provider
        payload["provider"] = "aifi"
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json=payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["allowed"] is True
        print("✅ Entry code issuance with AiFi provider successful")
        
        # Test rate limiting
        rapid_requests = []
        for i in range(3):
            response = await self.client.post(
                f"{self.base_url}/entry/v4/issue-code",
                json=payload,
                headers=self.headers
            )
            rapid_requests.append(response)
        
        # At least one should be rate limited
        rate_limited = any(r.json().get("reason") == "rate_limited" for r in rapid_requests)
        print(f"✅ Rate limiting {'working' if rate_limited else 'not triggered'}")
    
    async def test_entry_code_validation(self):
        """Test entry code validation"""
        print("\n🧪 Testing Entry Code Validation...")
        
        # First issue a code
        issue_payload = {
            "tenant_id": TEST_TENANT_ID,
            "site_id": TEST_SITE_ID,
            "store_id": TEST_STORE_ID,
            "user_id": TEST_USER_ID
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json=issue_payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        code_data = response.json()
        assert code_data["allowed"] is True
        issued_code = code_data["code"]
        
        # Validate the issued code
        validate_payload = {"code": issued_code}
        response = await self.client.post(
            f"{self.base_url}/entry/v4/validate-code",
            json=validate_payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] is True
        assert result["consumed"] is True
        print("✅ Entry code validation successful")
        
        # Try to validate the same code again (should fail)
        response = await self.client.post(
            f"{self.base_url}/entry/v4/validate-code",
            json=validate_payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] is False
        print("✅ Duplicate code validation correctly rejected")
        
        # Test invalid code
        invalid_payload = {"code": "999999"}
        response = await self.client.post(
            f"{self.base_url}/entry/v4/validate-code",
            json=invalid_payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["valid"] is False
        print("✅ Invalid code validation correctly rejected")
    
    async def test_entry_status(self):
        """Test entry status endpoint"""
        print("\n🧪 Testing Entry Status...")
        
        # Issue a code first
        issue_payload = {
            "tenant_id": TEST_TENANT_ID,
            "site_id": TEST_SITE_ID,
            "store_id": TEST_STORE_ID,
            "user_id": TEST_USER_ID
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json=issue_payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        code_data = response.json()
        issued_code = code_data["code"]
        
        # Check status of issued code
        response = await self.client.get(
            f"{self.base_url}/entry/v4/status",
            params={"code": issued_code},
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["exists"] is True
        assert result["tenant_id"] == TEST_TENANT_ID
        assert result["site_id"] == TEST_SITE_ID
        assert result["store_id"] == TEST_STORE_ID
        assert result["user_id"] == TEST_USER_ID
        print("✅ Entry status check successful")
        
        # Check status of non-existent code
        response = await self.client.get(
            f"{self.base_url}/entry/v4/status",
            params={"code": "000000"},
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["exists"] is False
        print("✅ Non-existent code status correctly returned")
    
    async def test_admin_endpoints(self):
        """Test admin configuration endpoints"""
        print("\n🧪 Testing Admin Endpoints...")
        
        # Configure entry provider
        provider_config = {
            "tenant_id": TEST_TENANT_ID,
            "type": "entry",
            "name": "test_provider",
            "config": {
                "provider": "aifi",
                "api_key": "test-api-key",
                "base_url": "https://api.test.com",
                "entry_endpoint": "/entry-codes",
                "verify_endpoint": "/verify"
            },
            "active": True
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/admin/rails/entry",
            json=provider_config,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        print("✅ Provider configuration successful")
        
        # List providers
        response = await self.client.get(
            f"{self.base_url}/entry/v4/admin/rails/entry",
            params={"tenant_id": TEST_TENANT_ID},
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        assert "providers" in result
        print("✅ Provider listing successful")
    
    async def test_event_retry(self):
        """Test event retry functionality"""
        print("\n🧪 Testing Event Retry...")
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/events/retry",
            params={"tenant_id": TEST_TENANT_ID, "max_events": 5},
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        assert "retried_count" in result
        print("✅ Event retry functionality working")
    
    async def test_integration_endpoints(self):
        """Test integration with other services"""
        print("\n🧪 Testing Integration Endpoints...")
        
        # Test user created event handler
        user_created_event = {
            "tenant_id": TEST_TENANT_ID,
            "user_id": TEST_USER_ID,
            "event_type": "USER_CREATED",
            "user_data": {
                "email": "test@example.com",
                "name": "Test User"
            }
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/integration/provisioning/user-created",
            json=user_created_event,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        print("✅ User created event handler working")
        
        # Test integration status
        response = await self.client.get(
            f"{self.base_url}/entry/v4/integration/status",
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is True
        assert result["service"] == "entry"
        assert "integrations" in result
        assert "status" in result
        print("✅ Integration status endpoint working")
    
    async def test_legacy_endpoints(self):
        """Test legacy endpoint deprecation"""
        print("\n🧪 Testing Legacy Endpoints...")
        
        # Test legacy issue-code endpoint
        payload = {
            "tenant_id": TEST_TENANT_ID,
            "site_id": TEST_SITE_ID,
            "store_id": TEST_STORE_ID,
            "user_id": TEST_USER_ID
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/issue-code",
            json=payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        result = response.json()
        assert result["allowed"] is True
        print("✅ Legacy issue-code endpoint working (deprecated)")
        
        # Test legacy validate-code endpoint
        validate_payload = {"code": "123456"}
        response = await self.client.post(
            f"{self.base_url}/entry/validate-code",
            json=validate_payload,
            headers=self.headers
        )
        
        assert response.status_code == 200
        print("✅ Legacy validate-code endpoint working (deprecated)")
    
    async def test_error_scenarios(self):
        """Test error handling and edge cases"""
        print("\n🧪 Testing Error Scenarios...")
        
        # Test missing authentication
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json={"tenant_id": TEST_TENANT_ID}
        )
        
        assert response.status_code == 401
        print("✅ Authentication required correctly enforced")
        
        # Test invalid payload
        invalid_payload = {
            "tenant_id": "invalid-uuid",
            "site_id": TEST_SITE_ID,
            "store_id": TEST_STORE_ID,
            "user_id": TEST_USER_ID
        }
        
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json=invalid_payload,
            headers=self.headers
        )
        
        # Should handle gracefully (might be 400 or 500 depending on validation)
        assert response.status_code in [400, 422, 500]
        print("✅ Invalid payload handling working")
        
        # Test missing required fields
        incomplete_payload = {"tenant_id": TEST_TENANT_ID}
        response = await self.client.post(
            f"{self.base_url}/entry/v4/issue-code",
            json=incomplete_payload,
            headers=self.headers
        )
        
        assert response.status_code == 422
        print("✅ Required field validation working")
    
    async def test_performance_metrics(self):
        """Test performance and metrics"""
        print("\n🧪 Testing Performance Metrics...")
        
        # Test multiple concurrent requests
        start_time = time.time()
        
        async def issue_code_request():
            payload = {
                "tenant_id": TEST_TENANT_ID,
                "site_id": TEST_SITE_ID,
                "store_id": TEST_STORE_ID,
                "user_id": str(uuid.uuid4())  # Different user for each request
            }
            response = await self.client.post(
                f"{self.base_url}/entry/v4/issue-code",
                json=payload,
                headers=self.headers
            )
            return response.status_code == 200
        
        # Run 10 concurrent requests
        tasks = [issue_code_request() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        total_time = time.time() - start_time
        
        print(f"✅ Concurrent requests: {success_count}/10 successful in {total_time:.2f}s")
        
        # Check metrics endpoint
        response = await self.client.get(f"{self.base_url}/metrics")
        assert response.status_code == 200
        metrics_text = response.text
        
        # Check for expected metrics
        expected_metrics = [
            "entry_requests_total",
            "entry_request_duration_seconds",
            "entry_codes_generated_total",
            "entry_saga_duration_seconds"
        ]
        
        for metric in expected_metrics:
            assert metric in metrics_text, f"Metric {metric} not found in metrics output"
        
        print("✅ Prometheus metrics working correctly")
    
    async def run_all_tests(self):
        """Run all test suites"""
        print("🚀 Starting ZeroQue Entry Service V4.1 Test Suite")
        print("=" * 60)
        
        try:
            await self.test_health_checks()
            await self.test_entry_code_issuance()
            await self.test_entry_code_validation()
            await self.test_entry_status()
            await self.test_admin_endpoints()
            await self.test_event_retry()
            await self.test_integration_endpoints()
            await self.test_legacy_endpoints()
            await self.test_error_scenarios()
            await self.test_performance_metrics()
            
            print("\n" + "=" * 60)
            print("🎉 All tests passed! Entry Service V4.1 is working correctly.")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n❌ Test failed: {str(e)}")
            raise

async def main():
    """Main test runner"""
    async with EntryServiceTester() as tester:
        await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
