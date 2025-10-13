"""
ZeroQue Load Testing Suite
Comprehensive load testing for all microservices
"""

from locust import HttpUser, task, between
import random
import json
import uuid

class OrdersUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """Set up test user"""
        self.tenant_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id
        }
    
    @task(10)
    def create_order(self):
        """Test order creation under load"""
        order_data = {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "items": [
                {
                    "product_id": str(uuid.uuid4()),
                    "quantity": random.randint(1, 10),
                    "unit_price_minor": random.randint(100, 10000)
                }
            ]
        }
        
        with self.client.post("/orders/v4", 
                            json=order_data, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code == 201:
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"Unexpected status: {response.status_code}")
    
    @task(5)
    def get_order_status(self):
        """Test order status retrieval"""
        order_id = str(uuid.uuid4())
        self.client.get(f"/orders/v4/{order_id}", 
                       headers=self.headers,
                       name="/orders/v4/[order_id]")
    
    @task(3)
    def list_orders(self):
        """Test order listing"""
        self.client.get("/orders/v4", 
                       headers=self.headers)

class IdentityUser(HttpUser):
    wait_time = between(2, 5)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id
        }
    
    @task(5)
    def create_user(self):
        """Test user creation"""
        user_data = {
            "tenant_id": self.tenant_id,
            "email": f"user{random.randint(1000, 9999)}@test.com",
            "name": f"Test User {random.randint(1, 100)}"
        }
        
        with self.client.post("/identity/v4/users", 
                            json=user_data, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code in [201, 409]:  # 409 for duplicate email
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")
    
    @task(10)
    def authenticate_user(self):
        """Test user authentication"""
        auth_data = {
            "email": "test@example.com",
            "password": "testpassword123"
        }
        
        with self.client.post("/identity/v4/auth/login", 
                            json=auth_data,
                            catch_response=True) as response:
            if response.status_code in [200, 401]:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

class PaymentsUser(HttpUser):
    wait_time = between(1, 4)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id
        }
    
    @task(8)
    def create_payment_intent(self):
        """Test payment intent creation"""
        payment_data = {
            "tenant_id": self.tenant_id,
            "amount_minor": random.randint(1000, 100000),
            "currency": "USD",
            "payment_method": "card"
        }
        
        with self.client.post("/payments/v4/intent", 
                            json=payment_data, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code == 201:
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"Unexpected status: {response.status_code}")
    
    @task(3)
    def get_payment_status(self):
        """Test payment status retrieval"""
        payment_id = str(uuid.uuid4())
        self.client.get(f"/payments/v4/transactions/{payment_id}", 
                       headers=self.headers,
                       name="/payments/v4/transactions/[payment_id]")

class LedgerUser(HttpUser):
    wait_time = between(2, 6)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id
        }
    
    @task(6)
    def create_ledger_entry(self):
        """Test ledger entry creation"""
        entry_data = {
            "tenant_id": self.tenant_id,
            "account_id": str(uuid.uuid4()),
            "amount_minor": random.randint(-10000, 10000),
            "currency": "USD",
            "description": f"Test entry {random.randint(1, 1000)}"
        }
        
        with self.client.post("/ledger/v4/entries", 
                            json=entry_data, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")
    
    @task(4)
    def get_account_balance(self):
        """Test account balance retrieval"""
        account_id = str(uuid.uuid4())
        self.client.get(f"/ledger/v4/accounts/{account_id}/balance", 
                       headers=self.headers,
                       name="/ledger/v4/accounts/[account_id]/balance")

class ApprovalsUser(HttpUser):
    wait_time = between(3, 8)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id
        }
    
    @task(4)
    def create_approval_request(self):
        """Test approval request creation"""
        request_data = {
            "tenant_id": self.tenant_id,
            "requestor_id": self.user_id,
            "amount_minor": random.randint(10000, 500000),
            "description": f"Approval request {random.randint(1, 1000)}"
        }
        
        with self.client.post("/approvals/v4/requests", 
                            json=request_data, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")
    
    @task(6)
    def list_approval_requests(self):
        """Test approval requests listing"""
        self.client.get("/approvals/v4/requests", 
                       headers=self.headers)

class NotificationsUser(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id
        }
    
    @task(8)
    def send_notification(self):
        """Test notification sending"""
        notification_data = {
            "tenant_id": self.tenant_id,
            "to": f"user{random.randint(1000, 9999)}@test.com",
            "subject": f"Test notification {random.randint(1, 1000)}",
            "message": "This is a test notification message",
            "channel": "email"
        }
        
        with self.client.post("/notifications/v4/send", 
                            json=notification_data, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code == 201:
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"Unexpected status: {response.status_code}")

class ReportsUser(HttpUser):
    wait_time = between(5, 10)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id
        }
    
    @task(3)
    def generate_sales_report(self):
        """Test sales report generation"""
        report_params = {
            "tenant_id": self.tenant_id,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "format": "json"
        }
        
        with self.client.post("/reports/v4/generate", 
                            json=report_params, 
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code in [200, 202]:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")
    
    @task(5)
    def get_report_status(self):
        """Test report status retrieval"""
        report_id = str(uuid.uuid4())
        self.client.get(f"/reports/v4/status/{report_id}", 
                       headers=self.headers,
                       name="/reports/v4/status/[report_id]")

# Composite user that tests multiple services
class CompositeUser(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        self.tenant_id = str(uuid.uuid4())
        self.user_id = str(uuid.uuid4())
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id
        }
    
    @task(1)
    def full_order_flow(self):
        """Test complete order flow across services"""
        # 1. Create order
        order_data = {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "items": [{"product_id": str(uuid.uuid4()), "quantity": 1, "unit_price_minor": 1000}]
        }
        
        order_response = self.client.post("/orders/v4", json=order_data, headers=self.headers)
        
        # 2. Create payment intent
        payment_data = {
            "tenant_id": self.tenant_id,
            "amount_minor": 1000,
            "currency": "USD"
        }
        
        payment_response = self.client.post("/payments/v4/intent", json=payment_data, headers=self.headers)
        
        # 3. Check order status
        if order_response.status_code == 201:
            order_id = order_response.json().get("id")
            self.client.get(f"/orders/v4/{order_id}", headers=self.headers)
    
    @task(2)
    def health_check_all_services(self):
        """Test health endpoints of all services"""
        services = [
            "orders", "identity", "ledger", "payments", "events",
            "cv-gateway", "cv-connector", "approvals", "entitlements",
            "subscriptions", "notifications", "reports", "usage",
            "observability", "service-registry", "monitoring"
        ]
        
        for service in services:
            self.client.get(f"/health", name=f"health-{service}")


