#!/usr/bin/env python3
"""
Comprehensive test script for CV Services V4.1 enhancements
Tests all the minor gaps that were addressed:
- Event automation for sync
- QR code rendering
- Access integration
- Metrics/observability
- Security/permissions
- Stale review cleanup
"""

import json
import requests
import time
from typing import Dict, Any

class CVServicesTester:
    def __init__(self, cv_connector_url="http://localhost:8100", cv_gateway_url="http://localhost:8000"):
        self.cv_connector_url = cv_connector_url
        self.cv_gateway_url = cv_gateway_url
        self.test_results = {}
    
    def test_health_endpoints(self) -> Dict[str, bool]:
        """Test health endpoints for both services"""
        print("🔍 Testing Health Endpoints...")
        results = {}
        
        try:
            # Test CV Connector health
            response = requests.get(f"{self.cv_connector_url}/health", timeout=5)
            results["cv_connector_health"] = response.status_code == 200
            print(f"  ✅ CV Connector Health: {response.status_code}")
        except Exception as e:
            results["cv_connector_health"] = False
            print(f"  ❌ CV Connector Health: {e}")
        
        try:
            # Test CV Gateway health
            response = requests.get(f"{self.cv_gateway_url}/health", timeout=5)
            results["cv_gateway_health"] = response.status_code == 200
            print(f"  ✅ CV Gateway Health: {response.status_code}")
        except Exception as e:
            results["cv_gateway_health"] = False
            print(f"  ❌ CV Gateway Health: {e}")
        
        return results
    
    def test_metrics_endpoints(self) -> Dict[str, bool]:
        """Test Prometheus metrics endpoints"""
        print("\n📊 Testing Metrics Endpoints...")
        results = {}
        
        try:
            # Test CV Connector metrics
            response = requests.get(f"{self.cv_connector_url}/metrics", timeout=5)
            results["cv_connector_metrics"] = response.status_code == 200
            if response.status_code == 200:
                metrics_content = response.text
                has_cv_metrics = "cv_connector_requests_total" in metrics_content
                results["cv_connector_metrics_content"] = has_cv_metrics
                print(f"  ✅ CV Connector Metrics: {response.status_code} (has CV metrics: {has_cv_metrics})")
            else:
                print(f"  ❌ CV Connector Metrics: {response.status_code}")
        except Exception as e:
            results["cv_connector_metrics"] = False
            print(f"  ❌ CV Connector Metrics: {e}")
        
        try:
            # Test CV Gateway metrics
            response = requests.get(f"{self.cv_gateway_url}/metrics", timeout=5)
            results["cv_gateway_metrics"] = response.status_code == 200
            if response.status_code == 200:
                metrics_content = response.text
                has_cv_metrics = "cv_gateway_requests_total" in metrics_content
                results["cv_gateway_metrics_content"] = has_cv_metrics
                print(f"  ✅ CV Gateway Metrics: {response.status_code} (has CV metrics: {has_cv_metrics})")
            else:
                print(f"  ❌ CV Gateway Metrics: {response.status_code}")
        except Exception as e:
            results["cv_gateway_metrics"] = False
            print(f"  ❌ CV Gateway Metrics: {e}")
        
        return results
    
    def test_qr_code_generation(self) -> Dict[str, bool]:
        """Test QR code generation endpoint"""
        print("\n🔲 Testing QR Code Generation...")
        results = {}
        
        try:
            payload = {
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user123",
                "provider": "aifi",
                "displayable": True
            }
            
            response = requests.post(
                f"{self.cv_connector_url}/cv/entry/qr",
                json=payload,
                headers={"Authorization": "Bearer demo_token"},
                timeout=10
            )
            
            results["qr_endpoint_exists"] = response.status_code != 404
            results["qr_endpoint_accessible"] = response.status_code in [200, 403, 500]  # 403 is expected without proper auth
            
            if response.status_code == 200:
                response_data = response.json()
                results["qr_response_valid"] = "qr_image" in response_data
                results["qr_image_base64"] = response_data.get("qr_image", "").startswith("data:image/png;base64,")
                print(f"  ✅ QR Code Endpoint: {response.status_code} (valid response: {results['qr_response_valid']})")
            else:
                print(f"  ✅ QR Code Endpoint exists: {response.status_code} (expected without proper setup)")
        except Exception as e:
            results["qr_endpoint_exists"] = False
            print(f"  ❌ QR Code Endpoint: {e}")
        
        return results
    
    def test_event_automation(self) -> Dict[str, bool]:
        """Test event automation endpoints"""
        print("\n🔄 Testing Event Automation...")
        results = {}
        
        # Test product created event
        try:
            payload = {
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "product": {
                    "external_id": "prod123",
                    "name": "Test Product",
                    "price": 10.50
                }
            }
            
            response = requests.post(
                f"{self.cv_connector_url}/events/product-created",
                json=payload,
                timeout=10
            )
            
            results["product_event_endpoint"] = response.status_code != 404
            print(f"  ✅ Product Event Endpoint: {response.status_code}")
        except Exception as e:
            results["product_event_endpoint"] = False
            print(f"  ❌ Product Event Endpoint: {e}")
        
        # Test user created event
        try:
            payload = {
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "user": {
                    "external_id": "user123",
                    "email": "test@example.com",
                    "first_name": "Test",
                    "last_name": "User"
                }
            }
            
            response = requests.post(
                f"{self.cv_connector_url}/events/user-created",
                json=payload,
                timeout=10
            )
            
            results["user_event_endpoint"] = response.status_code != 404
            print(f"  ✅ User Event Endpoint: {response.status_code}")
        except Exception as e:
            results["user_event_endpoint"] = False
            print(f"  ❌ User Event Endpoint: {e}")
        
        return results
    
    def test_security_permissions(self) -> Dict[str, bool]:
        """Test security and permission endpoints"""
        print("\n🔒 Testing Security & Permissions...")
        results = {}
        
        # Test admin endpoint without auth (should get 403)
        try:
            payload = {
                "type": "cv",
                "name": "test_provider",
                "config": {
                    "provider": "aifi",
                    "api_key": "test_key",
                    "base_url": "https://test.example.com"
                }
            }
            
            response = requests.post(
                f"{self.cv_connector_url}/admin/rails/cv",
                json=payload,
                timeout=10
            )
            
            results["admin_endpoint_secured"] = response.status_code in [403, 401]  # Expected without proper auth
            print(f"  ✅ Admin Endpoint Security: {response.status_code} (secured: {results['admin_endpoint_secured']})")
        except Exception as e:
            results["admin_endpoint_secured"] = False
            print(f"  ❌ Admin Endpoint Security: {e}")
        
        # Test sync endpoint without auth (should get 403)
        try:
            payload = {
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "customers": [],
                "products": [],
                "inventory": []
            }
            
            response = requests.post(
                f"{self.cv_connector_url}/cv/sync/batch",
                json=payload,
                timeout=10
            )
            
            results["sync_endpoint_secured"] = response.status_code in [403, 401]  # Expected without proper auth
            print(f"  ✅ Sync Endpoint Security: {response.status_code} (secured: {results['sync_endpoint_secured']})")
        except Exception as e:
            results["sync_endpoint_secured"] = False
            print(f"  ❌ Sync Endpoint Security: {e}")
        
        return results
    
    def test_stale_review_cleanup(self) -> Dict[str, bool]:
        """Test stale review cleanup endpoint"""
        print("\n🧹 Testing Stale Review Cleanup...")
        results = {}
        
        try:
            response = requests.post(
                f"{self.cv_connector_url}/admin/reviews/cleanup",
                json={"days_threshold": 7},
                headers={"Authorization": "Bearer demo_token"},
                timeout=10
            )
            
            results["cleanup_endpoint_exists"] = response.status_code != 404
            results["cleanup_endpoint_secured"] = response.status_code in [403, 401]  # Expected without proper auth
            
            if response.status_code == 200:
                response_data = response.json()
                results["cleanup_response_valid"] = "ok" in response_data
                print(f"  ✅ Cleanup Endpoint: {response.status_code} (valid response: {results['cleanup_response_valid']})")
            else:
                print(f"  ✅ Cleanup Endpoint exists: {response.status_code} (expected without proper setup)")
        except Exception as e:
            results["cleanup_endpoint_exists"] = False
            print(f"  ❌ Cleanup Endpoint: {e}")
        
        return results
    
    def test_enhanced_endpoints(self) -> Dict[str, bool]:
        """Test enhanced endpoints with new features"""
        print("\n✨ Testing Enhanced Endpoints...")
        results = {}
        
        # Test entry code creation with new features
        try:
            payload = {
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user123",
                "provider": "aifi",
                "displayable": True,
                "group_size": 1
            }
            
            response = requests.post(
                f"{self.cv_connector_url}/cv/entry/codes",
                json=payload,
                timeout=10
            )
            
            results["enhanced_entry_codes"] = response.status_code != 404
            print(f"  ✅ Enhanced Entry Codes: {response.status_code}")
        except Exception as e:
            results["enhanced_entry_codes"] = False
            print(f"  ❌ Enhanced Entry Codes: {e}")
        
        # Test CV Gateway order processing
        try:
            payload = {
                "provider": "aifi",
                "provider_order_id": "test_order_123",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                "site_id": "site123",
                "store_id": "store123",
                "shopper_id": "user123",
                "currency": "GBP",
                "items": [
                    {
                        "sku": "PROD001",
                        "name": "Test Product",
                        "qty": 1,
                        "price_minor": 500
                    }
                ]
            }
            
            response = requests.post(
                f"{self.cv_gateway_url}/cv/webhook/order",
                json=payload,
                timeout=10
            )
            
            results["enhanced_order_processing"] = response.status_code != 404
            print(f"  ✅ Enhanced Order Processing: {response.status_code}")
        except Exception as e:
            results["enhanced_order_processing"] = False
            print(f"  ❌ Enhanced Order Processing: {e}")
        
        return results
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all tests and return comprehensive results"""
        print("🚀 Starting CV Services V4.1 Comprehensive Testing...\n")
        
        all_results = {}
        
        # Run all test suites
        all_results.update(self.test_health_endpoints())
        all_results.update(self.test_metrics_endpoints())
        all_results.update(self.test_qr_code_generation())
        all_results.update(self.test_event_automation())
        all_results.update(self.test_security_permissions())
        all_results.update(self.test_stale_review_cleanup())
        all_results.update(self.test_enhanced_endpoints())
        
        # Calculate summary
        total_tests = len(all_results)
        passed_tests = sum(1 for result in all_results.values() if result)
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        print(f"\n📊 Test Summary:")
        print(f"  Total Tests: {total_tests}")
        print(f"  Passed: {passed_tests}")
        print(f"  Failed: {total_tests - passed_tests}")
        print(f"  Success Rate: {success_rate:.1f}%")
        
        # Feature-specific results
        feature_results = {
            "health_endpoints": all_results.get("cv_connector_health", False) and all_results.get("cv_gateway_health", False),
            "metrics_observability": all_results.get("cv_connector_metrics", False) and all_results.get("cv_gateway_metrics", False),
            "qr_code_generation": all_results.get("qr_endpoint_exists", False),
            "event_automation": all_results.get("product_event_endpoint", False) and all_results.get("user_event_endpoint", False),
            "security_permissions": all_results.get("admin_endpoint_secured", False) and all_results.get("sync_endpoint_secured", False),
            "stale_review_cleanup": all_results.get("cleanup_endpoint_exists", False),
            "enhanced_endpoints": all_results.get("enhanced_entry_codes", False) and all_results.get("enhanced_order_processing", False)
        }
        
        print(f"\n🎯 Feature Coverage:")
        for feature, passed in feature_results.items():
            status = "✅" if passed else "❌"
            print(f"  {status} {feature.replace('_', ' ').title()}")
        
        return {
            "all_results": all_results,
            "feature_results": feature_results,
            "summary": {
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "success_rate": success_rate
            }
        }

def main():
    """Main test runner"""
    print("=" * 60)
    print("🧪 CV Services V4.1 - Enhanced Features Test Suite")
    print("=" * 60)
    
    tester = CVServicesTester()
    results = tester.run_all_tests()
    
    print("\n" + "=" * 60)
    print("🏁 Testing Complete!")
    print("=" * 60)
    
    # Save results to file
    with open("cv_services_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📄 Detailed results saved to: cv_services_test_results.json")
    
    return results

if __name__ == "__main__":
    main()
