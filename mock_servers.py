#!/usr/bin/env python3
"""
Mock API servers for testing Postman collection
No database or dependencies required!
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from datetime import datetime
import uuid

class MockHandler(BaseHTTPRequestHandler):
    service_name = "Unknown"
    
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
        if "provisioning" in self.service_name.lower():
            if "tenant" in self.path:
                response["tenant_id"] = str(uuid.uuid4())
            elif "site" in self.path:
                response["site_id"] = str(uuid.uuid4())
            elif "store" in self.path:
                response["store_id"] = str(uuid.uuid4())
        elif "catalog" in self.service_name.lower():
            if "product" in self.path:
                response["product_id"] = str(uuid.uuid4())
        elif "order" in self.service_name.lower():
            response["order_id"] = str(uuid.uuid4())
        
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
        pass  # Suppress logs

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
    print("🚀 Starting ALL ZeroQue Mock Services")
    print("=" * 60)
    print()
    
    threads = []
    for port, name in services:
        thread = threading.Thread(target=start_server, args=(port, name), daemon=True)
        thread.start()
        threads.append(thread)
    
    print()
    print("=" * 60)
    print("✅ ALL 21 SERVICES RUNNING!")
    print("=" * 60)
    print()
    print("Test with:")
    print("  curl http://localhost:8000/health")
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

