#!/usr/bin/env python3
"""
Comprehensive test script for ZeroQue Events Service V2
Tests all endpoints, sagas, and integration scenarios
"""

import asyncio
import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List
import httpx

# Test configuration
BASE_URL = "http://localhost:8087"
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440003"

class EventsServiceTester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.test_results = []
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    def log_test(self, test_name: str, success: bool, details: str = ""):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.test_results.append(result)
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {details}")
    
    async def test_health_endpoints(self):
        """Test health and readiness endpoints"""
        try:
            # Health check
            response = await self.client.get(f"{self.base_url}/events/v4/health")
            if response.status_code == 200:
                self.log_test("Health Check", True, "Service is healthy")
            else:
                self.log_test("Health Check", False, f"Status: {response.status_code}")
            
            # Readiness check
            response = await self.client.get(f"{self.base_url}/events/v4/readiness")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ready":
                    self.log_test("Readiness Check", True, "Service is ready")
                else:
                    self.log_test("Readiness Check", False, f"Status: {data.get('status')}")
            else:
                self.log_test("Readiness Check", False, f"Status: {response.status_code}")
            
            # Metrics endpoint
            response = await self.client.get(f"{self.base_url}/events/v4/metrics")
            if response.status_code == 200:
                self.log_test("Metrics Endpoint", True, "Metrics accessible")
            else:
                self.log_test("Metrics Endpoint", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Health Endpoints", False, f"Error: {str(e)}")
    
    async def test_event_publishing(self):
        """Test event publishing functionality"""
        try:
            # Test valid event publishing
            event_payload = {
                "tenant_id": TEST_TENANT_ID,
                "event_type": "USER_CREATED",
                "event_data": {
                    "user_id": str(uuid.uuid4()),
                    "email": "test@example.com",
                    "name": "Test User"
                },
                "metadata": {
                    "source": "test_script",
                    "version": "1.0"
                }
            }
            
            response = await self.client.post(
                f"{self.base_url}/events/v4/publish",
                json=event_payload,
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "published":
                    self.log_test("Event Publishing", True, f"Event published: {data.get('event_id')}")
                    return data.get("event_id")
                else:
                    self.log_test("Event Publishing", False, f"Unexpected status: {data.get('status')}")
            else:
                self.log_test("Event Publishing", False, f"Status: {response.status_code}, Response: {response.text}")
                
        except Exception as e:
            self.log_test("Event Publishing", False, f"Error: {str(e)}")
        
        return None
    
    async def test_event_history(self):
        """Test event history retrieval"""
        try:
            # Get event history
            response = await self.client.get(
                f"{self.base_url}/events/v4/history",
                params={
                    "tenant_id": TEST_TENANT_ID,
                    "limit": 10
                },
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if "events" in data and "total_count" in data:
                    self.log_test("Event History", True, f"Retrieved {len(data['events'])} events, total: {data['total_count']}")
                    return data
                else:
                    self.log_test("Event History", False, "Invalid response format")
            else:
                self.log_test("Event History", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Event History", False, f"Error: {str(e)}")
        
        return None
    
    async def test_event_filtering(self):
        """Test event filtering by type and status"""
        try:
            # Test filtering by event type
            response = await self.client.get(
                f"{self.base_url}/events/v4/history",
                params={
                    "tenant_id": TEST_TENANT_ID,
                    "event_type": "USER_CREATED",
                    "limit": 5
                },
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                filtered_events = [e for e in data.get("events", []) if e.get("event_type") == "USER_CREATED"]
                if len(filtered_events) == len(data.get("events", [])):
                    self.log_test("Event Type Filtering", True, f"All {len(filtered_events)} events match filter")
                else:
                    self.log_test("Event Type Filtering", False, "Filter not applied correctly")
            else:
                self.log_test("Event Type Filtering", False, f"Status: {response.status_code}")
            
            # Test filtering by status
            response = await self.client.get(
                f"{self.base_url}/events/v4/history",
                params={
                    "tenant_id": TEST_TENANT_ID,
                    "status": "published",
                    "limit": 5
                },
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                filtered_events = [e for e in data.get("events", []) if e.get("status") == "published"]
                if len(filtered_events) == len(data.get("events", [])) or len(data.get("events", [])) == 0:
                    self.log_test("Event Status Filtering", True, f"Status filter working")
                else:
                    self.log_test("Event Status Filtering", False, "Status filter not applied correctly")
            else:
                self.log_test("Event Status Filtering", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Event Filtering", False, f"Error: {str(e)}")
    
    async def test_event_retry(self):
        """Test event retry functionality"""
        try:
            retry_payload = {
                "tenant_id": TEST_TENANT_ID,
                "max_events": 5
            }
            
            response = await self.client.post(
                f"{self.base_url}/events/v4/retry",
                json=retry_payload,
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok") and "retried_count" in data:
                    self.log_test("Event Retry", True, f"Retried {data.get('retried_count')} events")
                else:
                    self.log_test("Event Retry", False, f"Invalid response: {data}")
            else:
                self.log_test("Event Retry", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Event Retry", False, f"Error: {str(e)}")
    
    async def test_event_stats(self):
        """Test event statistics"""
        try:
            response = await self.client.get(
                f"{self.base_url}/events/v4/stats",
                params={
                    "tenant_id": TEST_TENANT_ID,
                    "start_date": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                    "end_date": datetime.utcnow().isoformat()
                },
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if "stats" in data and "period" in data:
                    stats = data["stats"]
                    self.log_test("Event Stats", True, f"Total events: {stats.get('total_events', 0)}")
                else:
                    self.log_test("Event Stats", False, "Invalid response format")
            else:
                self.log_test("Event Stats", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Event Stats", False, f"Error: {str(e)}")
    
    async def test_event_subscriptions(self):
        """Test event subscription management"""
        try:
            # Create subscription
            subscription_payload = {
                "tenant_id": TEST_TENANT_ID,
                "service_name": "test_service",
                "event_type": "USER_CREATED",
                "queue_name": "user_events_queue"
            }
            
            response = await self.client.post(
                f"{self.base_url}/events/v4/admin/subscriptions",
                json=subscription_payload,
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "created":
                    subscription_id = data.get("subscription_id")
                    self.log_test("Create Subscription", True, f"Created subscription: {subscription_id}")
                    
                    # List subscriptions
                    response = await self.client.get(
                        f"{self.base_url}/events/v4/admin/subscriptions",
                        params={"tenant_id": TEST_TENANT_ID},
                        headers={"Authorization": "Bearer test-token"}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if "subscriptions" in data:
                            self.log_test("List Subscriptions", True, f"Found {len(data['subscriptions'])} subscriptions")
                        else:
                            self.log_test("List Subscriptions", False, "Invalid response format")
                    else:
                        self.log_test("List Subscriptions", False, f"Status: {response.status_code}")
                else:
                    self.log_test("Create Subscription", False, f"Unexpected status: {data.get('status')}")
            else:
                self.log_test("Create Subscription", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Event Subscriptions", False, f"Error: {str(e)}")
    
    async def test_legacy_endpoints(self):
        """Test legacy endpoint compatibility"""
        try:
            # Test legacy publish endpoint
            event_payload = {
                "tenant_id": TEST_TENANT_ID,
                "event_type": "LEGACY_TEST",
                "event_data": {"test": "legacy"}
            }
            
            response = await self.client.post(
                f"{self.base_url}/publish",
                json=event_payload,
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                self.log_test("Legacy Publish Endpoint", True, "Legacy endpoint working")
            else:
                self.log_test("Legacy Publish Endpoint", False, f"Status: {response.status_code}")
            
            # Test legacy history endpoint
            response = await self.client.get(
                f"{self.base_url}/history",
                params={"tenant_id": TEST_TENANT_ID},
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                self.log_test("Legacy History Endpoint", True, "Legacy endpoint working")
            else:
                self.log_test("Legacy History Endpoint", False, f"Status: {response.status_code}")
            
            # Test legacy stats endpoint
            response = await self.client.get(
                f"{self.base_url}/stats",
                params={"tenant_id": TEST_TENANT_ID},
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code == 200:
                self.log_test("Legacy Stats Endpoint", True, "Legacy endpoint working")
            else:
                self.log_test("Legacy Stats Endpoint", False, f"Status: {response.status_code}")
                
        except Exception as e:
            self.log_test("Legacy Endpoints", False, f"Error: {str(e)}")
    
    async def test_error_handling(self):
        """Test error handling scenarios"""
        try:
            # Test invalid tenant ID
            response = await self.client.post(
                f"{self.base_url}/events/v4/publish",
                json={
                    "tenant_id": "invalid-uuid",
                    "event_type": "TEST",
                    "event_data": {}
                },
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code in [400, 422]:
                self.log_test("Invalid Tenant ID", True, "Properly rejected invalid tenant ID")
            else:
                self.log_test("Invalid Tenant ID", False, f"Should reject invalid tenant ID, got: {response.status_code}")
            
            # Test missing event type
            response = await self.client.post(
                f"{self.base_url}/events/v4/publish",
                json={
                    "tenant_id": TEST_TENANT_ID,
                    "event_data": {}
                },
                headers={"Authorization": "Bearer test-token"}
            )
            
            if response.status_code in [400, 422]:
                self.log_test("Missing Event Type", True, "Properly rejected missing event type")
            else:
                self.log_test("Missing Event Type", False, f"Should reject missing event type, got: {response.status_code}")
            
            # Test unauthorized access
            response = await self.client.post(
                f"{self.base_url}/events/v4/publish",
                json={
                    "tenant_id": TEST_TENANT_ID,
                    "event_type": "TEST",
                    "event_data": {}
                }
                # No authorization header
            )
            
            if response.status_code == 401:
                self.log_test("Unauthorized Access", True, "Properly rejected unauthorized access")
            else:
                self.log_test("Unauthorized Access", False, f"Should reject unauthorized access, got: {response.status_code}")
                
        except Exception as e:
            self.log_test("Error Handling", False, f"Error: {str(e)}")
    
    async def test_performance(self):
        """Test performance with multiple concurrent requests"""
        try:
            async def publish_event():
                event_payload = {
                    "tenant_id": TEST_TENANT_ID,
                    "event_type": "PERFORMANCE_TEST",
                    "event_data": {"timestamp": datetime.utcnow().isoformat()}
                }
                
                response = await self.client.post(
                    f"{self.base_url}/events/v4/publish",
                    json=event_payload,
                    headers={"Authorization": "Bearer test-token"}
                )
                return response.status_code == 200
            
            # Test concurrent publishing
            start_time = time.time()
            tasks = [publish_event() for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()
            
            success_count = sum(1 for r in results if r is True)
            duration = end_time - start_time
            
            if success_count >= 8:  # Allow for some failures
                self.log_test("Concurrent Publishing", True, f"{success_count}/10 successful in {duration:.2f}s")
            else:
                self.log_test("Concurrent Publishing", False, f"Only {success_count}/10 successful")
                
        except Exception as e:
            self.log_test("Performance Test", False, f"Error: {str(e)}")
    
    async def run_all_tests(self):
        """Run all test scenarios"""
        print("🚀 Starting Events Service V2 Comprehensive Tests")
        print("=" * 60)
        
        # Core functionality tests
        await self.test_health_endpoints()
        await self.test_event_publishing()
        await self.test_event_history()
        await self.test_event_filtering()
        await self.test_event_retry()
        await self.test_event_stats()
        
        # Admin functionality tests
        await self.test_event_subscriptions()
        
        # Compatibility tests
        await self.test_legacy_endpoints()
        
        # Error handling tests
        await self.test_error_handling()
        
        # Performance tests
        await self.test_performance()
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 Test Summary")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print("\n❌ Failed Tests:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['details']}")
        
        return passed_tests == total_tests

async def main():
    """Main test runner"""
    async with EventsServiceTester() as tester:
        success = await tester.run_all_tests()
        return 0 if success else 1

if __name__ == "__main__":
    import sys
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
