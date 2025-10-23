#!/usr/bin/env python3
"""
Enhanced Mock API servers for testing Postman collection
Returns proper JSON responses for all endpoints
"""
import json
import uuid
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                "status": "healthy",
                "service": self.service_name,
                "timestamp": datetime.now().isoformat()
            }
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                "service": self.service_name,
                "uptime": "1h",
                "requests": 100
            }
            self.wfile.write(json.dumps(response).encode())
        elif 'provisioning' in self.service_name.lower():
            self.handle_provisioning_get()
        elif 'catalog' in self.service_name.lower():
            self.handle_catalog_get()
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                "message": f"{self.service_name} is running",
                "path": self.path,
                "method": "GET"
            }
            self.wfile.write(json.dumps(response).encode())
    
    def handle_provisioning_get(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        if self.path == '/provisioning/tenants':
            response = [
                {"tenant_id": "demo-tenant-1", "name": "Demo Manufacturing Co", "type": "customer"},
                {"tenant_id": "demo-tenant-2", "name": "Demo Retail Corp", "type": "customer"}
            ]
        elif self.path == '/provisioning/sites':
            response = [
                {"site_id": "demo-site-1", "tenant_id": "demo-tenant-1", "name": "Main Site"},
                {"site_id": "demo-site-2", "tenant_id": "demo-tenant-2", "name": "Branch Site"}
            ]
        elif self.path == '/provisioning/users':
            response = [
                {"user_id": "demo-user-1", "tenant_id": "demo-tenant-1", "email": "admin@demo.com"},
                {"user_id": "demo-user-2", "tenant_id": "demo-tenant-2", "email": "user@demo.com"}
            ]
        elif self.path == '/provisioning/stores':
            response = [
                {"store_id": "demo-store-1", "site_id": "demo-site-1", "name": "Main Store"},
                {"store_id": "demo-store-2", "site_id": "demo-site-2", "name": "Branch Store"}
            ]
        elif self.path == '/provisioning/vendors':
            response = [
                {"vendor_id": "demo-vendor-1", "name": "Demo Vendor Inc", "status": "active"},
                {"vendor_id": "demo-vendor-2", "name": "Another Vendor", "status": "active"}
            ]
        elif self.path == '/provisioning/roles':
            response = [
                {"role_id": "demo-role-1", "code": "admin", "name": "Administrator"},
                {"role_id": "demo-role-2", "code": "user", "name": "User"}
            ]
        elif self.path == '/provisioning/cost-centres':
            response = [
                {"cost_centre_id": "demo-cc-1", "name": "IT Department", "status": "active"},
                {"cost_centre_id": "demo-cc-2", "name": "HR Department", "status": "active"}
            ]
        else:
            response = {
                "message": f"{self.service_name} is running",
                "path": self.path,
                "method": "GET"
            }
        
        self.wfile.write(json.dumps(response).encode())
    
    def handle_catalog_get(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        if self.path == '/products':
            response = [
                {"product_id": "demo-product-1", "name": "Demo Product 1", "price": 100, "sku": "DP001"},
                {"product_id": "demo-product-2", "name": "Demo Product 2", "price": 200, "sku": "DP002"},
                {"product_id": "demo-product-3", "name": "Demo Product 3", "price": 300, "sku": "DP003"}
            ]
        elif self.path == '/products/variants':
            response = [
                {"variant_id": "demo-variant-1", "product_id": "demo-product-1", "name": "Small Size", "price": 90},
                {"variant_id": "demo-variant-2", "product_id": "demo-product-1", "name": "Large Size", "price": 120}
            ]
        elif self.path.startswith('/products/') and '/variants' in self.path:
            response = [
                {"variant_id": "demo-variant-1", "product_id": self.path.split('/')[-2], "name": "Small Size", "price": 90},
                {"variant_id": "demo-variant-2", "product_id": self.path.split('/')[-2], "name": "Large Size", "price": 120}
            ]
        else:
            response = {
                "message": f"{self.service_name} is running",
                "path": self.path,
                "method": "GET"
            }
        
        self.wfile.write(json.dumps(response).encode())
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        self.send_response(201)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        response = {
            "status": "success",
            "service": self.service_name,
            "id": str(uuid.uuid4()),
            "created_at": datetime.now().isoformat()
        }
        
        # Add service-specific IDs
        if 'provisioning' in self.service_name.lower():
            if 'tenant' in self.path:
                response["tenant_id"] = str(uuid.uuid4())
            elif 'site' in self.path:
                response["site_id"] = str(uuid.uuid4())
            elif 'store' in self.path:
                response["store_id"] = str(uuid.uuid4())
            elif 'user' in self.path:
                response["user_id"] = str(uuid.uuid4())
        elif 'catalog' in self.service_name.lower():
            if 'product' in self.path and 'variant' in self.path:
                response["variant_id"] = str(uuid.uuid4())
                response["product_id"] = "demo-product-1"
        
        self.wfile.write(json.dumps(response).encode())
    
    def do_PUT(self):
        self.do_POST()
    
    def do_DELETE(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {"status": "deleted"}
        self.wfile.write(json.dumps(response).encode())
    
    def log_message(self, format, *args):
        pass

def create_handler(service_name):
    class CustomHandler(MockHandler):
        pass
    CustomHandler.service_name = service_name
    return CustomHandler

def start_server(port, service_name):
    handler = create_handler(service_name)
    server = HTTPServer(('localhost', port), handler)
    print(f"✓ {service_name:20s} started on port {port}")
    server.serve_forever()

# Service definitions
services = [
    (8000, "Provisioning Service"),
    (8001, "Catalog Service"),
    (8002, "Orders Service"),
    (8006, "Pricing Service"),
    (8080, "CV Gateway Service"),
    (8084, "Approvals Service"),
    (8085, "Events Service"),
    (8086, "Ledger Service"),
    (8212, "Subscriptions Service"),
    (8213, "Payments Service"),
    (8214, "Billing Service"),
    (8215, "Notifications Service"),
    (8216, "CV Connector Service"),
    (8217, "Reports Service"),
    (8218, "Entry Service"),
    (8219, "Usage Service"),
    (8220, "Observability Service"),
    (8221, "Monitoring Service"),
    (8222, "Service Registry"),
    (8223, "Entitlements Service"),
    (8224, "Identity Service"),
]

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Starting ENHANCED ZeroQue Mock Services")
    print("=" * 60)
    print()
    
    threads = []
    for port, name in services:
        thread = threading.Thread(target=start_server, args=(port, name), daemon=True)
        thread.start()
        threads.append(thread)
    
    print()
    print("=" * 60)
    print("✅ ALL 21 SERVICES RUNNING WITH PROPER JSON!")
    print("=" * 60)
    print()
    print("Test with:")
    print("  curl http://localhost:8001/products")
    print("  curl http://localhost:8001/products/variants")
    print("  curl http://localhost:8000/provisioning/tenants")
    print()
    print("Ready for Postman testing!")
    print("Press Ctrl+C to stop all services")
    print()
    
    # Keep running
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping all services...")
        print("✓ All services stopped")
