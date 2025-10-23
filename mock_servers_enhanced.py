#!/usr/bin/env python3
"""Enhanced mock servers with service-specific responses"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from datetime import datetime, timedelta
import uuid
import re

class EnhancedMockHandler(BaseHTTPRequestHandler):
    service_name = "Unknown"
    service_port = 8000
    
    def do_GET(self):
        # Health endpoint
        if self.path == '/health':
            self.send_json_response(200, {
                "status": "healthy",
                "service": self.service_name,
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0"
            })
            return
        
        # Metrics endpoint
        if self.path == '/metrics':
            self.send_json_response(200, {
                "service": self.service_name,
                "uptime_seconds": 3600,
                "requests_total": 1234,
                "requests_per_second": 10.5
            })
            return
        
        # Service-specific GET endpoints
        response = self.get_service_response('GET', self.path)
        self.send_json_response(200, response)
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = {}
        if content_length > 0:
            body_bytes = self.rfile.read(content_length)
            try:
                body = json.loads(body_bytes.decode('utf-8'))
            except:
                body = {}
        
        response = self.get_service_response('POST', self.path, body)
        self.send_json_response(201, response)
    
    def do_PUT(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = {}
        if content_length > 0:
            body_bytes = self.rfile.read(content_length)
            try:
                body = json.loads(body_bytes.decode('utf-8'))
            except:
                body = {}
        
        response = self.get_service_response('PUT', self.path, body)
        self.send_json_response(200, response)
    
    def do_DELETE(self):
        self.send_json_response(200, {
            "status": "deleted",
            "message": "Resource deleted successfully"
        })
    
    def send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def get_service_response(self, method, path, body=None):
        """Generate service-specific responses"""
        
        # PROVISIONING SERVICE (8000)
        if self.service_port == 8000:
            if 'tenants' in path:
                if method == 'POST':
                    return {
                        "tenant_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Demo Tenant'),
                        "company_name": body.get('company_name', 'Demo Company'),
                        "industry": body.get('industry', 'technology'),
                        "status": "active",
                        "created_at": datetime.now().isoformat()
                    }
                else:  # GET list
                    return {
                        "tenants": [
                            {
                                "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Manufacturing Co",
                                "status": "active"
                            }
                        ],
                        "total": 1
                    }
            
            elif 'sites' in path:
                if method in ['POST', 'PUT']:
                    return {
                        "site_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Main Site'),
                        "site_type": body.get('site_type', 'office'),
                        "status": "active",
                        "created_at": datetime.now().isoformat()
                    }
                else:
                    return {
                        "sites": [
                            {"site_id": str(uuid.uuid4()), "name": "Main Factory", "site_type": "factory"}
                        ],
                        "total": 1
                    }
            
            elif 'stores' in path:
                if method in ['POST', 'PUT']:
                    return {
                        "store_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Main Store'),
                        "store_type": body.get('store_type', 'retail'),
                        "status": "active"
                    }
                else:
                    return {"stores": [], "total": 0}
            
            elif 'users' in path:
                if 'bulk-import' in path:
                    return {
                        "imported": 10,
                        "failed": 0,
                        "users": [{"user_id": str(uuid.uuid4()), "email": "user@example.com"}]
                    }
                elif method in ['POST', 'PUT']:
                    return {
                        "user_id": str(uuid.uuid4()),
                        "email": body.get('email', 'user@example.com'),
                        "display_name": body.get('display_name', 'Test User'),
                        "status": "active"
                    }
                else:
                    return {"users": [], "total": 0}
            
            elif 'roles' in path:
                if method in ['POST', 'PUT']:
                    return {
                        "role_id": str(uuid.uuid4()),
                        "code": body.get('code', 'manager'),
                        "name": body.get('name', 'Manager'),
                        "description": body.get('description', '')
                    }
                else:
                    return {"roles": [], "total": 0}
            
            elif 'vendors' in path:
                if method in ['POST', 'PUT']:
                    return {
                        "vendor_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Vendor Inc'),
                        "contact_email": body.get('contact_email', 'vendor@example.com')
                    }
                else:
                    return {"vendors": [], "total": 0}
            
            elif 'cost-centres' in path:
                if method == 'POST':
                    return {
                        "cost_centre_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Operations'),
                        "budget_minor": body.get('budget_minor', 500000)
                    }
                else:
                    return {"cost_centres": [], "total": 0}
        
        # CATALOG SERVICE (8001)
        elif self.service_port == 8001:
            if 'products' in path and 'barcode-sync' not in path and 'variants' not in path:
                if method == 'POST':
                    return {
                        "product_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Sample Product'),
                        "sku": body.get('sku', f"SKU-{uuid.uuid4().hex[:8]}"),
                        "barcode": body.get('barcode', ''),
                        "base_price_minor": body.get('base_price_minor', 1000),
                        "currency": body.get('currency', 'GBP'),
                        "vendor_id": body.get('vendor_id', ''),
                        "status": "active",
                        "created_at": datetime.now().isoformat()
                    }
                else:  # GET
                    return {
                        "products": [
                            {
                                "product_id": str(uuid.uuid4()),
                                "name": "Premium Notebook",
                                "sku": "NB-001",
                                "base_price_minor": 500
                            }
                        ],
                        "total": 1,
                        "page": 1,
                        "page_size": 20
                    }
            
            elif 'variants' in path:
                if method == 'POST':
                    return {
                        "variant_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Variant'),
                        "sku": body.get('sku', ''),
                        "price_adjustment_minor": body.get('price_adjustment_minor', 0)
                    }
            
            elif 'categories' in path:
                if method == 'POST':
                    return {
                        "category_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Category'),
                        "description": body.get('description', '')
                    }
                else:
                    return {"categories": [], "total": 0}
            
            elif 'bundles' in path:
                if method == 'POST':
                    return {
                        "bundle_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Bundle'),
                        "bundle_sku": body.get('bundle_sku', ''),
                        "base_price_minor": body.get('base_price_minor', 0)
                    }
                else:
                    return {"bundles": [], "total": 0}
            
            elif 'search' in path:
                return {
                    "results": [
                        {
                            "product_id": str(uuid.uuid4()),
                            "name": "Search Result",
                            "sku": "SEARCH-001",
                            "relevance": 0.95
                        }
                    ],
                    "total": 1
                }
        
        # ORDERS SERVICE (8002)
        elif self.service_port == 8002:
            if 'orders' in path:
                if method == 'POST':
                    return {
                        "order_id": str(uuid.uuid4()),
                        "tenant_id": body.get('tenant_id', ''),
                        "site_id": body.get('site_id', ''),
                        "store_id": body.get('store_id', ''),
                        "customer_id": body.get('customer_id', ''),
                        "order_type": body.get('order_type', 'retail'),
                        "status": "pending",
                        "total_amount_minor": 1000,
                        "currency": "GBP",
                        "items": body.get('items', []),
                        "created_at": datetime.now().isoformat()
                    }
                elif method == 'PUT':
                    return {
                        "order_id": path.split('/')[-1],
                        "status": "updated",
                        "fulfillment_status": body.get('fulfillment_status', 'completed'),
                        "updated_at": datetime.now().isoformat()
                    }
                else:  # GET
                    return {
                        "orders": [
                            {
                                "order_id": str(uuid.uuid4()),
                                "status": "completed",
                                "total_amount_minor": 1000,
                                "currency": "GBP"
                            }
                        ],
                        "total": 1
                    }
        
        # PRICING SERVICE (8006)
        elif self.service_port == 8006:
            if 'pricebooks' in path and 'rules' not in path:
                if method == 'POST':
                    return {
                        "pricebook_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Standard Pricing'),
                        "currency": body.get('currency', 'GBP'),
                        "is_default": body.get('is_default', False),
                        "created_at": datetime.now().isoformat()
                    }
                else:
                    return {
                        "pricebooks": [
                            {
                                "pricebook_id": str(uuid.uuid4()),
                                "name": "Standard Pricing",
                                "currency": "GBP",
                                "is_default": True
                            }
                        ],
                        "total": 1
                    }
            
            elif 'rules' in path:
                if method == 'POST':
                    return {
                        "rule_id": str(uuid.uuid4()),
                        "pricebook_id": body.get('pricebook_id', ''),
                        "product_id": body.get('product_id', ''),
                        "rule_type": body.get('rule_type', 'fixed'),
                        "rule_value": body.get('rule_value', 0)
                    }
            
            elif 'calculate' in path:
                return {
                    "product_id": body.get('product_id', ''),
                    "quantity": body.get('quantity', 1),
                    "base_price_minor": body.get('base_price_minor', 1000),
                    "final_price_minor": 950,
                    "discount_minor": 50,
                    "currency": "GBP"
                }
        
        # ENTRY SERVICE (8218)
        elif self.service_port == 8218:
            if 'issue-code' in path:
                return {
                    "entry_code": f"ENTRY-{uuid.uuid4().hex[:8].upper()}",
                    "user_id": body.get('user_id', ''),
                    "store_id": body.get('store_id', ''),
                    "expires_at": (datetime.now() + timedelta(minutes=30)).isoformat(),
                    "qr_code": "data:image/png;base64,iVBORw0KG...",
                    "status": "active"
                }
            
            elif 'validate-code' in path:
                return {
                    "valid": True,
                    "entry_code": body.get('code', ''),
                    "user_id": str(uuid.uuid4()),
                    "store_id": body.get('store_id', ''),
                    "validated_at": datetime.now().isoformat()
                }
            
            elif 'codes' in path:
                return {
                    "codes": [
                        {
                            "entry_code": "ENTRY-ABC123",
                            "status": "active",
                            "expires_at": datetime.now().isoformat()
                        }
                    ],
                    "total": 1
                }
            
            elif 'status' in path:
                code = path.split('/')[-1]
                return {
                    "entry_code": code,
                    "status": "active",
                    "user_id": str(uuid.uuid4()),
                    "created_at": datetime.now().isoformat()
                }
        
        # SUBSCRIPTIONS SERVICE (8212)
        elif self.service_port == 8212:
            if 'features' in path and 'plans' not in path:
                if method == 'POST':
                    return {
                        "feature_id": str(uuid.uuid4()),
                        "code": body.get('code', ''),
                        "name": body.get('name', ''),
                        "description": body.get('description', '')
                    }
            
            elif 'plans' in path and 'features' not in path:
                if method == 'POST':
                    return {
                        "plan_id": str(uuid.uuid4()),
                        "code": body.get('code', ''),
                        "name": body.get('name', ''),
                        "price_yearly_minor": body.get('price_yearly_minor', 0),
                        "currency": body.get('currency', 'GBP')
                    }
                else:
                    return {
                        "plans": [
                            {
                                "plan_id": str(uuid.uuid4()),
                                "code": "core",
                                "name": "Core Plan",
                                "price_yearly_minor": 99900
                            }
                        ],
                        "total": 1
                    }
            
            elif 'features' in path and 'plans' in path:
                if method == 'PUT':
                    return {
                        "status": "added",
                        "plan_code": path.split('/')[-3],
                        "feature_code": path.split('/')[-1]
                    }
                elif method == 'GET':
                    return {
                        "features": [
                            {
                                "feature_code": "sku_management",
                                "name": "SKU Management",
                                "enabled": True
                            }
                        ]
                    }
                elif method == 'DELETE':
                    return {"status": "removed"}
            
            elif 'subscriptions' in path:
                if method == 'POST':
                    return {
                        "subscription_id": str(uuid.uuid4()),
                        "tenant_id": body.get('tenant_id', ''),
                        "plan_code": body.get('plan_code', 'core'),
                        "status": "active",
                        "billing_cycle": body.get('billing_cycle', 'yearly'),
                        "starts_at": datetime.now().isoformat(),
                        "ends_at": (datetime.now() + timedelta(days=365)).isoformat()
                    }
                elif 'renew' in path:
                    return {
                        "subscription_id": path.split('/')[-2],
                        "status": "renewed",
                        "renewed_at": datetime.now().isoformat()
                    }
                elif 'cancel' in path:
                    return {
                        "subscription_id": path.split('/')[-2],
                        "status": "cancelled",
                        "cancelled_at": datetime.now().isoformat()
                    }
                else:  # GET
                    tenant_id = path.split('/')[-1]
                    return {
                        "subscription_id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "plan_code": "core",
                        "status": "active"
                    }
        
        # ENTITLEMENTS SERVICE (8223)
        elif self.service_port == 8223:
            if 'check' in path:
                return {
                    "entitled": True,
                    "feature_code": "advanced_analytics",
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "remaining_quota": 1000
                }
            
            elif 'usage' in path:
                if method == 'POST' and 'record' in path:
                    return {
                        "recorded": True,
                        "feature_code": body.get('feature_code', ''),
                        "quantity": body.get('quantity', 1),
                        "remaining_quota": 999
                    }
                else:  # GET usage
                    return {
                        "tenant_id": path.split('/')[-1],
                        "usage": [
                            {
                                "feature_code": "api_calls",
                                "used": 150,
                                "limit": 1000
                            }
                        ]
                    }
            
            elif 'cache' in path and 'clear' in path:
                return {
                    "status": "cleared",
                    "tenant_id": body.get('tenant_id', '')
                }
        
        # IDENTITY SERVICE (8224)
        elif self.service_port == 8224:
            if 'users' in path:
                if method == 'POST':
                    return {
                        "user_id": str(uuid.uuid4()),
                        "email": body.get('email', ''),
                        "display_name": body.get('display_name', ''),
                        "tenant_id": body.get('tenant_id', ''),
                        "status": "active",
                        "created_at": datetime.now().isoformat()
                    }
                else:
                    return {
                        "users": [
                            {
                                "user_id": str(uuid.uuid4()),
                                "email": "user@example.com",
                                "display_name": "John Doe"
                            }
                        ],
                        "total": 1
                    }
            
            elif 'roles' in path and 'role-assignments' not in path:
                if method == 'POST':
                    return {
                        "role_id": str(uuid.uuid4()),
                        "name": body.get('name', 'Admin'),
                        "permissions": body.get('permissions', [])
                    }
                else:
                    return {
                        "roles": [
                            {"role_id": str(uuid.uuid4()), "name": "Admin"}
                        ],
                        "total": 1
                    }
            
            elif 'role-assignments' in path:
                if method == 'POST':
                    return {
                        "assignment_id": str(uuid.uuid4()),
                        "user_id": body.get('user_id', ''),
                        "role_id": body.get('role_id', ''),
                        "assigned_at": datetime.now().isoformat()
                    }
            
            elif 'token' in path:
                return {
                    "token": f"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.{uuid.uuid4().hex}",
                    "expires_in": 3600,
                    "token_type": "Bearer"
                }
            
            elif 'reports' in path:
                return {
                    "total_users": 25,
                    "active_users": 20,
                    "roles": 5
                }
            
            elif 'oauth' in path:
                if 'providers' in path:
                    if method == 'POST':
                        return {
                            "provider_id": str(uuid.uuid4()),
                            "provider": body.get('provider', 'google'),
                            "status": "configured"
                        }
                    else:
                        return {"providers": [], "total": 0}
                elif 'initiate' in path:
                    return {
                        "authorization_url": "https://oauth.example.com/authorize?client_id=xxx",
                        "state": uuid.uuid4().hex
                    }
                elif 'callback' in path:
                    return {
                        "user_id": str(uuid.uuid4()),
                        "email": "user@example.com",
                        "token": "jwt_token_here"
                    }
        
        # Default response
        return {
            "service": self.service_name,
            "method": method,
            "path": path,
            "message": "Request processed successfully",
            "timestamp": datetime.now().isoformat()
        }
    
    def log_message(self, format, *args):
        pass  # Suppress logs

def create_handler(service_name, port):
    class CustomHandler(EnhancedMockHandler):
        pass
    CustomHandler.service_name = service_name
    CustomHandler.service_port = port
    return CustomHandler

def start_server(port, service_name):
    handler = create_handler(service_name, port)
    server = HTTPServer(('localhost', port), handler)
    print(f"✓ {service_name:25s} on port {port}")
    server.serve_forever()

# Core 8 services
services = [
    (8000, "Provisioning Service"),
    (8001, "Catalog Service"),
    (8002, "Orders Service"),
    (8006, "Pricing Service"),
    (8212, "Subscriptions Service"),
    (8218, "Entry Service"),
    (8223, "Entitlements Service"),
    (8224, "Identity Service"),
]

if __name__ == "__main__":
    print("=" * 65)
    print("🚀 Starting ZeroQue Core 8 Services (Enhanced)")
    print("=" * 65)
    print()
    
    threads = []
    for port, name in services:
        thread = threading.Thread(target=start_server, args=(port, name), daemon=True)
        thread.start()
        threads.append(thread)
    
    print()
    print("=" * 65)
    print("✅ ALL 8 SERVICES RUNNING WITH PROPER RESPONSES!")
    print("=" * 65)
    print()
    print("Services respond with proper data (not generic):")
    print("  • GET requests: List data with pagination")
    print("  • POST requests: Create with full resource details")
    print("  • PUT requests: Update with confirmation")
    print()
    print("Ready for Postman!")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping all services...")

