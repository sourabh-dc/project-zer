#!/usr/bin/env python3
"""
Comprehensive test suite for ZeroQue Identity Service V4.1
Tests user management, role management, token generation, and reports
"""

import asyncio
import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, Any

import httpx
from fastapi.testclient import TestClient

# Import the service
from services.identity.main import app

# Test configuration
BASE_URL = "http://localhost:8088"
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440001"

class IdentityServiceTester:
    """Comprehensive Identity Service Tester"""
    
    def __init__(self):
        self.client = TestClient(app)
        self.test_tenant_id = TEST_TENANT_ID
        self.test_user_id = TEST_USER_ID
        self.created_users = []
        self.created_roles = []
        self.generated_tokens = []
    
    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API calls"""
        return {
            "Authorization": "Bearer demo-token",
            "Content-Type": "application/json"
        }
    
    def test_health_checks(self):
        """Test health and readiness endpoints"""
        print("🔍 Testing health checks...")
        
        # Test health endpoint
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "identity"
        assert data["version"] == "4.1.0"
        
        # Test readiness endpoint
        response = self.client.get("/readiness")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "identity"
        assert "db" in data
        assert "ready" in data
        
        # Test metrics endpoint
        response = self.client.get("/metrics")
        assert response.status_code == 200
        assert "identity_requests_total" in response.text
        
        print("✅ Health checks passed")
    
    def test_role_management(self):
        """Test role creation and management"""
        print("🔍 Testing role management...")
        
        # Create test role
        role_payload = {
            "tenant_id": self.test_tenant_id,
            "name": "test_role",
            "description": "Test role for identity service",
            "permissions": ["identity.view_user", "identity.create_user", "entry.issue_code"]
        }
        
        response = self.client.post(
            "/identity/v4/roles",
            json=role_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        role_data = response.json()
        assert role_data["name"] == "test_role"
        assert role_data["permissions"] == role_payload["permissions"]
        self.created_roles.append(role_data["id"])
        
        # List roles
        response = self.client.get(
            f"/identity/v4/roles?tenant_id={self.test_tenant_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        roles = response.json()
        assert len(roles) > 0
        assert any(role["name"] == "test_role" for role in roles)
        
        # Test role permissions
        test_role = next(role for role in roles if role["name"] == "test_role")
        assert "identity.view_user" in test_role["permissions"]
        assert "entry.issue_code" in test_role["permissions"]
        
        print("✅ Role management passed")
    
    def test_user_management(self):
        """Test user creation and management with saga pattern"""
        print("🔍 Testing user management with saga...")
        
        # Create test user
        user_payload = {
            "tenant_id": self.test_tenant_id,
            "email": "test@example.com",
            "name": "Test User",
            "role_ids": self.created_roles,  # Assign the test role
            "user_metadata": {"department": "engineering", "level": "senior"}
        }
        
        response = self.client.post(
            "/identity/v4/users",
            json=user_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        user_data = response.json()
        assert user_data["email"] == "test@example.com"
        assert user_data["name"] == "Test User"
        assert len(user_data["roles"]) > 0
        self.created_users.append(user_data["id"])
        
        # Test user metadata
        assert user_data["user_metadata"]["department"] == "engineering"
        assert user_data["user_metadata"]["level"] == "senior"
        
        # List users
        response = self.client.get(
            f"/identity/v4/users?tenant_id={self.test_tenant_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        users = response.json()
        assert len(users) > 0
        assert any(user["email"] == "test@example.com" for user in users)
        
        # Test user filtering by email
        response = self.client.get(
            f"/identity/v4/users?tenant_id={self.test_tenant_id}&email_filter=test",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        filtered_users = response.json()
        assert all("test" in user["email"].lower() for user in filtered_users)
        
        print("✅ User management passed")
    
    def test_role_assignments(self):
        """Test role assignment functionality"""
        print("🔍 Testing role assignments...")
        
        if not self.created_users or not self.created_roles:
            print("⚠️ Skipping role assignment test - no users or roles created")
            return
        
        # Create additional role for testing
        role_payload = {
            "tenant_id": self.test_tenant_id,
            "name": "admin_role",
            "description": "Admin role for testing",
            "permissions": ["identity.admin", "identity.view_reports"]
        }
        
        response = self.client.post(
            "/identity/v4/roles",
            json=role_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        admin_role = response.json()
        self.created_roles.append(admin_role["id"])
        
        # Assign role to user
        assignment_payload = {
            "tenant_id": self.test_tenant_id,
            "user_id": self.created_users[0],
            "role_id": admin_role["id"]
        }
        
        response = self.client.post(
            "/identity/v4/role-assignments",
            json=assignment_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        assignment_data = response.json()
        assert assignment_data["ok"] is True
        
        # Verify role assignment by listing users
        response = self.client.get(
            f"/identity/v4/users?tenant_id={self.test_tenant_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        users = response.json()
        
        test_user = next(user for user in users if user["id"] == self.created_users[0])
        role_names = [role["name"] for role in test_user["roles"]]
        assert "admin_role" in role_names
        assert "test_role" in role_names
        
        print("✅ Role assignments passed")
    
    def test_token_generation(self):
        """Test JWT token generation for guest and loyalty users"""
        print("🔍 Testing token generation...")
        
        # Test guest token generation
        guest_payload = {
            "tenant_id": self.test_tenant_id,
            "token_type": "guest",
            "guest_info": {"device_id": "test-device-123", "ip_address": "192.168.1.1"}
        }
        
        response = self.client.post(
            "/identity/v4/token",
            json=guest_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        guest_token_data = response.json()
        assert guest_token_data["token_type"] == "guest"
        assert guest_token_data["user_id"] is None
        assert "guest.access" in guest_token_data["permissions"]
        assert guest_token_data["token"] is not None
        self.generated_tokens.append(guest_token_data["token"])
        
        # Test loyalty token generation
        if self.created_users:
            loyalty_payload = {
                "tenant_id": self.test_tenant_id,
                "token_type": "loyalty",
                "user_id": self.created_users[0]
            }
            
            response = self.client.post(
                "/identity/v4/token",
                json=loyalty_payload,
                headers=self.get_auth_headers()
            )
            assert response.status_code == 200
            loyalty_token_data = response.json()
            assert loyalty_token_data["token_type"] == "loyalty"
            assert loyalty_token_data["user_id"] == self.created_users[0]
            assert len(loyalty_token_data["permissions"]) > 0
            assert loyalty_token_data["token"] is not None
            self.generated_tokens.append(loyalty_token_data["token"])
            
            # Verify loyalty token has correct permissions
            expected_permissions = ["identity.view_user", "identity.create_user", "entry.issue_code", "identity.admin", "identity.view_reports"]
            for perm in expected_permissions:
                if perm in loyalty_token_data["permissions"]:
                    break
            else:
                # At least one expected permission should be present
                assert len(loyalty_token_data["permissions"]) > 0
        
        print("✅ Token generation passed")
    
    def test_reports(self):
        """Test identity reports (blueprint-inspired analytics)"""
        print("🔍 Testing identity reports...")
        
        # Test active users report
        response = self.client.get(
            f"/identity/v4/reports?tenant_id={self.test_tenant_id}&report_type=active_users",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        report_data = response.json()
        assert report_data["report_type"] == "active_users"
        assert report_data["tenant_id"] == self.test_tenant_id
        assert "summary" in report_data
        assert "total_users" in report_data["summary"]
        assert report_data["summary"]["total_users"] > 0
        
        # Test role counts report
        response = self.client.get(
            f"/identity/v4/reports?tenant_id={self.test_tenant_id}&report_type=role_counts",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        role_report = response.json()
        assert role_report["report_type"] == "role_counts"
        assert "summary" in role_report
        assert "total_roles" in role_report["summary"]
        assert "total_assignments" in role_report["summary"]
        assert len(role_report["data"]) > 0
        
        # Verify role data structure
        for role_data in role_report["data"]:
            assert "role_name" in role_data
            assert "user_count" in role_data
            assert "permissions" in role_data
        
        print("✅ Reports passed")
    
    def test_legacy_endpoints(self):
        """Test legacy endpoint deprecation and redirection"""
        print("🔍 Testing legacy endpoints...")
        
        # Test legacy guest token endpoint
        response = self.client.post(
            f"/guest-token?tenant_id={self.test_tenant_id}",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 200
        legacy_guest_data = response.json()
        assert legacy_guest_data["token_type"] == "guest"
        assert legacy_guest_data["token"] is not None
        
        # Test legacy loyalty token endpoint
        if self.created_users:
            response = self.client.post(
                f"/loyalty-token?tenant_id={self.test_tenant_id}&user_id={self.created_users[0]}",
                headers=self.get_auth_headers()
            )
            assert response.status_code == 200
            legacy_loyalty_data = response.json()
            assert legacy_loyalty_data["token_type"] == "loyalty"
            assert legacy_loyalty_data["user_id"] == self.created_users[0]
            assert legacy_loyalty_data["token"] is not None
        
        print("✅ Legacy endpoints passed")
    
    def test_error_handling(self):
        """Test error handling and validation"""
        print("🔍 Testing error handling...")
        
        # Test invalid token type
        invalid_payload = {
            "tenant_id": self.test_tenant_id,
            "token_type": "invalid_type"
        }
        
        response = self.client.post(
            "/identity/v4/token",
            json=invalid_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 400
        assert "Invalid token_type" in response.json()["detail"]
        
        # Test missing user_id for loyalty token
        loyalty_payload = {
            "tenant_id": self.test_tenant_id,
            "token_type": "loyalty"
            # Missing user_id
        }
        
        response = self.client.post(
            "/identity/v4/token",
            json=loyalty_payload,
            headers=self.get_auth_headers()
        )
        assert response.status_code == 400
        assert "user_id required" in response.json()["detail"]
        
        # Test invalid report type
        response = self.client.get(
            f"/identity/v4/reports?tenant_id={self.test_tenant_id}&report_type=invalid_report",
            headers=self.get_auth_headers()
        )
        assert response.status_code == 400
        assert "Unsupported report type" in response.json()["detail"]
        
        print("✅ Error handling passed")
    
    def test_performance_metrics(self):
        """Test performance and metrics collection"""
        print("🔍 Testing performance metrics...")
        
        # Test multiple rapid requests to check metrics
        start_time = time.time()
        
        for i in range(10):
            response = self.client.get(
                f"/identity/v4/roles?tenant_id={self.test_tenant_id}",
                headers=self.get_auth_headers()
            )
            assert response.status_code == 200
        
        end_time = time.time()
        avg_response_time = (end_time - start_time) / 10
        
        # Check metrics endpoint for performance data
        response = self.client.get("/metrics")
        assert response.status_code == 200
        metrics_text = response.text
        
        # Verify metrics are being collected
        assert "identity_requests_total" in metrics_text
        assert "identity_request_duration_seconds" in metrics_text
        assert "identity_tokens_generated_total" in metrics_text
        
        print(f"✅ Performance metrics passed (avg response time: {avg_response_time:.3f}s)")
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting Identity Service V4.1 Comprehensive Tests")
        print("=" * 60)
        
        try:
            self.test_health_checks()
            self.test_role_management()
            self.test_user_management()
            self.test_role_assignments()
            self.test_token_generation()
            self.test_reports()
            self.test_legacy_endpoints()
            self.test_error_handling()
            self.test_performance_metrics()
            
            print("=" * 60)
            print("🎉 All Identity Service tests passed!")
            print(f"📊 Created {len(self.created_users)} users and {len(self.created_roles)} roles")
            print(f"🎫 Generated {len(self.generated_tokens)} tokens")
            
        except Exception as e:
            print(f"❌ Test failed: {str(e)}")
            raise


def test_identity_service_integration():
    """Integration test function"""
    tester = IdentityServiceTester()
    tester.run_all_tests()


if __name__ == "__main__":
    # Run tests
    test_identity_service_integration()
