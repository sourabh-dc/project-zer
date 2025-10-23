#!/usr/bin/env python3
"""
Realistic Mock Servers - Mimics Real Database Schema
All fields match the actual database models from main.py files
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from datetime import datetime, timedelta
import uuid
import re
import hashlib

class RealisticMockHandler(BaseHTTPRequestHandler):
    service_name = "Unknown"
    service_port = 8000
    
    # In-memory storage to track created resources
    storage = {
        'tenants': {},
        'sites': {},
        'stores': {},
        'users': {},
        'roles': {},
        'vendors': {},
        'cost_centres': {},
        'products': {},
        'orders': {},
        'pricebooks': {},
        'subscriptions': {},
        'plans': {},
        'features': {},
        'entry_codes': {},
    }
    
    def do_GET(self):
        if self.path == '/health':
            self.send_json(200, {
                "status": "healthy",
                "service": self.service_name,
                "version": "4.1.0",
                "timestamp": datetime.now().isoformat()
            })
            return
        
        if self.path == '/metrics':
            self.send_json(200, {
                "service": self.service_name,
                "uptime_seconds": 3600,
                "requests_total": 1234,
                "active_connections": 5
            })
            return
        
        if self.path == '/readiness':
            self.send_json(200, {"ready": True, "service": self.service_name})
            return
        
        response = self.handle_get_request(self.path)
        self.send_json(200, response)
    
    def do_POST(self):
        body = self.read_body()
        response = self.handle_post_request(self.path, body)
        self.send_json(201, response)
    
    def do_PUT(self):
        body = self.read_body()
        response = self.handle_put_request(self.path, body)
        self.send_json(200, response)
    
    def do_DELETE(self):
        self.send_json(200, {"status": "deleted", "message": "Resource deleted successfully"})
    
    def read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body_bytes = self.rfile.read(content_length)
            try:
                return json.loads(body_bytes.decode('utf-8'))
            except:
                return {}
        return {}
    
    def send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())
    
    def handle_get_request(self, path):
        """Handle GET requests with realistic responses"""
        
        # PROVISIONING SERVICE (8000)
        if self.service_port == 8000:
            if path == '/provisioning/tenants':
                return {
                    "tenants": list(self.storage['tenants'].values()),
                    "total": len(self.storage['tenants']),
                    "page": 1,
                    "page_size": 20
                }
            
            elif path == '/provisioning/sites':
                return {
                    "sites": list(self.storage['sites'].values()),
                    "total": len(self.storage['sites'])
                }
            
            elif path == '/provisioning/stores':
                return {
                    "stores": list(self.storage['stores'].values()),
                    "total": len(self.storage['stores'])
                }
            
            elif path == '/provisioning/users':
                return {
                    "users": list(self.storage['users'].values()),
                    "total": len(self.storage['users'])
                }
            
            elif path == '/provisioning/roles':
                return {
                    "roles": list(self.storage['roles'].values()),
                    "total": len(self.storage['roles'])
                }
            
            elif path == '/provisioning/vendors':
                return {
                    "vendors": list(self.storage['vendors'].values()),
                    "total": len(self.storage['vendors'])
                }
            
            elif path == '/provisioning/cost-centres':
                return {
                    "cost_centres": list(self.storage['cost_centres'].values()),
                    "total": len(self.storage['cost_centres'])
                }
        
        # CATALOG SERVICE (8001)
        elif self.service_port == 8001:
            if path == '/products':
                return {
                    "products": list(self.storage['products'].values()),
                    "total": len(self.storage['products']),
                    "page": 1,
                    "page_size": 20
                }
            
            elif '/products/' in path and not any(x in path for x in ['variants', 'barcode-sync']):
                product_id = path.split('/')[-1]
                product = self.storage['products'].get(product_id)
                if product:
                    return product
                return {"error": "Product not found"}
            
            elif path == '/categories':
                return {"categories": [], "total": 0}
            
            elif path == '/bundles':
                return {"bundles": [], "total": 0}
        
        # ORDERS SERVICE (8002)
        elif self.service_port == 8002:
            if path == '/orders':
                return {
                    "orders": list(self.storage['orders'].values()),
                    "total": len(self.storage['orders']),
                    "page": 1,
                    "page_size": 20
                }
            
            elif '/orders/' in path:
                order_id = path.split('/')[-1]
                order = self.storage['orders'].get(order_id)
                if order:
                    return order
                return {"error": "Order not found"}
        
        # PRICING SERVICE (8006)
        elif self.service_port == 8006:
            if path.startswith('/pricebooks'):
                return {
                    "pricebooks": list(self.storage['pricebooks'].values()),
                    "total": len(self.storage['pricebooks'])
                }
        
        # SUBSCRIPTIONS SERVICE (8212)
        elif self.service_port == 8212:
            if path == '/subscriptions/v2/plans':
                return {
                    "plans": list(self.storage['plans'].values()) or [
                        {
                            "id": 1,
                            "code": "core",
                            "name": "Core Plan",
                            "description": "Essential features",
                            "price_yearly_minor": 99900,
                            "currency": "GBP",
                            "active": True,
                            "created_at": datetime.now().isoformat(),
                            "updated_at": None
                        }
                    ],
                    "total": max(1, len(self.storage['plans']))
                }
            
            elif '/features' in path and 'plans' in path:
                # GET plan features
                return {
                    "features": [
                        {
                            "code": "sku_management",
                            "name": "SKU Management",
                            "description": "Manage product SKUs",
                            "enabled": True,
                            "rate_limit": 1000
                        },
                        {
                            "code": "multi_site",
                            "name": "Multi-Site Support",
                            "description": "Support for multiple sites",
                            "enabled": True
                        }
                    ],
                    "total": 2
                }
            
            elif '/subscriptions/' in path and 'v2/subscriptions' in path:
                tenant_id = path.split('/')[-1]
                return {
                    "subscription_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "plan_code": "core",
                    "payment_method": "stripe",
                    "status": "active",
                    "external_id": f"sub_{tenant_id}",
                    "current_period_start": datetime.now().isoformat(),
                    "current_period_end": (datetime.now() + timedelta(days=365)).isoformat(),
                    "trial_end": None,
                    "canceled_at": None,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
        
        # ENTRY SERVICE (8218)
        elif self.service_port == 8218:
            if path == '/entry/v4/codes':
                return {
                    "codes": list(self.storage['entry_codes'].values()),
                    "total": len(self.storage['entry_codes'])
                }
            
            elif '/entry/v4/status/' in path:
                code = path.split('/')[-1]
                entry = self.storage['entry_codes'].get(code)
                if entry:
                    return entry
                return {
                    "code": code,
                    "status": "not_found"
                }
        
        # ENTITLEMENTS SERVICE (8223)
        elif self.service_port == 8223:
            if '/entitlements/v2/check' in path:
                return {
                    "entitled": True,
                    "feature_code": "advanced_analytics",
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "plan_code": "core",
                    "rate_limit": 1000,
                    "remaining_quota": 950,
                    "checked_at": datetime.now().isoformat()
                }
            
            elif '/entitlements/v2/usage/' in path:
                tenant_id = path.split('/')[-1]
                return {
                    "tenant_id": tenant_id,
                    "usage": [
                        {
                            "feature_code": "api_calls",
                            "used": 150,
                            "limit": 1000,
                            "period": "monthly"
                        },
                        {
                            "feature_code": "storage_gb",
                            "used": 25,
                            "limit": 100,
                            "period": "monthly"
                        }
                    ],
                    "total": 2
                }
        
        # IDENTITY SERVICE (8224)
        elif self.service_port == 8224:
            if path == '/identity/v4/users':
                return {
                    "users": list(self.storage['users'].values()),
                    "total": len(self.storage['users'])
                }
            
            elif path == '/identity/v4/roles':
                return {
                    "roles": list(self.storage['roles'].values()) if self.storage['roles'] else [
                        {
                            "id": str(uuid.uuid4()),
                            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                            "name": "Admin",
                            "description": "Administrator role",
                            "permissions": ["*"],
                            "created_at": datetime.now().isoformat()
                        }
                    ],
                    "total": max(1, len(self.storage['roles']))
                }
            
            elif path == '/identity/v4/reports':
                return {
                    "total_users": len(self.storage['users']),
                    "active_users": len([u for u in self.storage['users'].values() if u.get('active', True)]),
                    "total_roles": len(self.storage['roles']),
                    "generated_at": datetime.now().isoformat()
                }
            
            elif path == '/identity/v4/oauth/providers':
                return {"providers": [], "total": 0}
        
        # Default
        return {
            "message": "Endpoint not fully mocked yet",
            "path": path,
            "service": self.service_name
        }
    
    def handle_post_request(self, path, body):
        """Handle POST requests with full database schema"""
        
        # PROVISIONING SERVICE (8000)
        if self.service_port == 8000:
            if '/provisioning/tenants' in path:
                tenant_id = str(uuid.uuid4())
                tenant = {
                    "tenant_id": tenant_id,
                    "name": body.get('name', 'Demo Tenant'),
                    "type": body.get('tenant_type', 'customer'),
                    "active": True,
                    "tenant_metadata": body.get('metadata', {}),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['tenants'][tenant_id] = tenant
                return tenant
            
            elif '/provisioning/cost-centres' in path:
                cc_id = f"cc_{uuid.uuid4().hex[:12]}"
                cost_centre = {
                    "cost_centre_id": cc_id,
                    "tenant_id": body.get('tenant_id', ''),
                    "name": body.get('name', ''),
                    "budget_minor": body.get('budget_minor', 0),
                    "spent_minor": 0,
                    "currency_code": "GBP",
                    "status": "active",
                    "created_at": datetime.now().isoformat()
                }
                self.storage['cost_centres'][cc_id] = cost_centre
                return cost_centre
            
            elif '/provisioning/users/bulk-import' in path:
                users_data = body.get('users', [])
                imported_users = []
                for user_data in users_data:
                    user_id = str(uuid.uuid4())
                    api_key = f"zq_key_{hashlib.md5(user_id.encode()).hexdigest()[:16]}" if body.get('auto_generate_api_keys') else None
                    user = {
                        "user_id": user_id,
                        "tenant_id": body.get('tenant_id', ''),
                        "email": user_data.get('email', ''),
                        "display_name": user_data.get('display_name', ''),
                        "active": True,
                        "api_key": api_key,
                        "api_key_created_at": datetime.now().isoformat() if api_key else None,
                        "permissions": user_data.get('permissions', []),
                        "created_at": datetime.now().isoformat()
                    }
                    self.storage['users'][user_id] = user
                    imported_users.append(user)
                
                return {
                    "imported_count": len(imported_users),
                    "failed_count": 0,
                    "users": imported_users,
                    "message": f"Successfully imported {len(imported_users)} users"
                }
        
        # CATALOG SERVICE (8001)
        elif self.service_port == 8001:
            if path == '/products':
                product_id = str(uuid.uuid4())
                product = {
                    "product_id": product_id,
                    "tenant_id": body.get('tenant_id', '550e8400-e29b-41d4-a716-446655440000'),
                    "vendor_id": body.get('vendor_id', ''),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "sku": body.get('sku', ''),
                    "barcode": body.get('barcode'),
                    "category_id": body.get('category_id'),
                    "brand": body.get('brand'),
                    "base_price_minor": body.get('base_price_minor', 0),
                    "currency": body.get('currency', 'GBP'),
                    "weight_grams": body.get('weight_grams'),
                    "dimensions_cm": body.get('dimensions_cm'),
                    "is_active": True,
                    "metadata_json": body.get('metadata'),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['products'][product_id] = product
                return product
            
            elif '/products/' in path and '/variants' in path:
                return {
                    "variant_id": str(uuid.uuid4()),
                    "product_id": path.split('/')[2],
                    "name": body.get('name', ''),
                    "sku": body.get('sku', ''),
                    "price_adjustment_minor": body.get('price_adjustment_minor', 0),
                    "attributes": body.get('attributes', {}),
                    "is_active": True,
                    "created_at": datetime.now().isoformat()
                }
            
            elif path == '/categories':
                return {
                    "category_id": str(uuid.uuid4()),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "parent_category_id": body.get('parent_category_id'),
                    "metadata": body.get('metadata', {}),
                    "created_at": datetime.now().isoformat()
                }
            
            elif path == '/bundles':
                return {
                    "bundle_id": str(uuid.uuid4()),
                    "tenant_id": body.get('tenant_id', '550e8400-e29b-41d4-a716-446655440000'),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "bundle_sku": body.get('bundle_sku', ''),
                    "bundle_type": body.get('bundle_type', 'bundle'),
                    "base_price_minor": body.get('base_price_minor', 0),
                    "currency": body.get('currency', 'GBP'),
                    "is_active": True,
                    "components": body.get('components', []),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
            
            elif path == '/search':
                # Return realistic search results
                query = body.get('query', '')
                return {
                    "results": [
                        {
                            "product_id": str(uuid.uuid4()),
                            "name": f"Premium {query.title()} Product",
                            "sku": f"SKU-{uuid.uuid4().hex[:8].upper()}",
                            "base_price_minor": 1999,
                            "currency": "GBP",
                            "relevance_score": 0.95
                        }
                    ],
                    "total": 1,
                    "query": query
                }
        
        # ORDERS SERVICE (8002)
        elif self.service_port == 8002:
            if path == '/orders':
                order_id = str(uuid.uuid4())
                order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                order = {
                    "order_id": order_id,
                    "tenant_id": body.get('tenant_id', ''),
                    "site_id": body.get('site_id'),
                    "store_id": body.get('store_id'),
                    "customer_id": body.get('customer_id', ''),
                    "order_number": order_number,
                    "order_status": "pending",
                    "order_type": body.get('order_type', 'retail'),
                    "total_amount_minor": sum(item.get('unit_price_minor', 0) * item.get('quantity', 1) for item in body.get('items', [])),
                    "currency": body.get('currency', 'GBP'),
                    "payment_status": "pending",
                    "fulfillment_status": "pending",
                    "shipping_address": body.get('shipping_address'),
                    "billing_address": body.get('billing_address'),
                    "order_metadata": body.get('metadata', {}),
                    "items": [
                        {
                            "item_id": str(uuid.uuid4()),
                            "order_id": order_id,
                            "product_id": item.get('product_id', ''),
                            "variant_id": item.get('variant_id'),
                            "quantity": item.get('quantity', 1),
                            "unit_price_minor": item.get('unit_price_minor', 0),
                            "discount_minor": item.get('discount_minor', 0),
                            "tax_minor": item.get('tax_minor', 0),
                            "total_minor": item.get('unit_price_minor', 0) * item.get('quantity', 1)
                        }
                        for item in body.get('items', [])
                    ],
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['orders'][order_id] = order
                return order
        
        # PRICING SERVICE (8006)
        elif self.service_port == 8006:
            if path == '/pricebooks':
                pricebook_id = str(uuid.uuid4())
                pricebook = {
                    "pricebook_id": pricebook_id,
                    "tenant_id": body.get('tenant_id', '550e8400-e29b-41d4-a716-446655440000'),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "currency": body.get('currency', 'GBP'),
                    "is_active": True,
                    "custom_metadata": body.get('metadata', {}),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['pricebooks'][pricebook_id] = pricebook
                return pricebook
            
            elif '/pricebooks/' in path and '/rules' in path:
                return {
                    "rule_id": str(uuid.uuid4()),
                    "pricebook_id": body.get('pricebook_id', ''),
                    "product_id": body.get('product_id'),
                    "variant_id": body.get('variant_id'),
                    "rule_type": body.get('rule_type', 'fixed'),
                    "rule_value": body.get('rule_value', 0.0),
                    "min_quantity": body.get('min_quantity'),
                    "max_quantity": body.get('max_quantity'),
                    "valid_from": body.get('valid_from'),
                    "valid_until": body.get('valid_until'),
                    "is_active": True,
                    "custom_metadata": body.get('metadata', {}),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
            
            elif path == '/calculate':
                base_price = body.get('base_price_minor', 0)
                quantity = body.get('quantity', 1)
                # Apply simple discount logic
                discount = int(base_price * 0.05) if quantity > 5 else 0
                return {
                    "product_id": body.get('product_id', ''),
                    "quantity": quantity,
                    "base_price_minor": base_price,
                    "discount_minor": discount,
                    "final_price_minor": base_price - discount,
                    "currency": "GBP",
                    "calculated_at": datetime.now().isoformat()
                }
        
        # SUBSCRIPTIONS SERVICE (8212)
        elif self.service_port == 8212:
            if path == '/subscriptions/v2/features':
                return {
                    "feature_id": str(uuid.uuid4()),
                    "code": body.get('code', ''),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "category": body.get('category'),
                    "active": True,
                    "created_at": datetime.now().isoformat()
                }
            
            elif path == '/subscriptions/v2/plans':
                plan_id = len(self.storage['plans']) + 1
                plan = {
                    "id": plan_id,
                    "code": body.get('code', ''),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "price_yearly_minor": body.get('price_yearly_minor', 0),
                    "currency": body.get('currency', 'GBP'),
                    "active": True,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['plans'][plan_id] = plan
                return plan
            
            elif path == '/subscriptions/v2/subscriptions':
                return {
                    "id": len(self.storage['subscriptions']) + 1,
                    "subscription_id": str(uuid.uuid4()),
                    "tenant_id": body.get('tenant_id', ''),
                    "plan_code": body.get('plan_code', 'core'),
                    "payment_method": body.get('payment_method', 'stripe'),
                    "status": "active",
                    "external_id": f"sub_{body.get('tenant_id', '')}_{int(datetime.now().timestamp())}",
                    "current_period_start": datetime.now().isoformat(),
                    "current_period_end": (datetime.now() + timedelta(days=365)).isoformat(),
                    "trial_end": None,
                    "canceled_at": None,
                    "billing_cycle": body.get('billing_cycle', 'yearly'),
                    "auto_renew": body.get('auto_renew', True),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
            
            elif '/renew' in path:
                tenant_id = path.split('/')[-2]
                return {
                    "subscription_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "status": "renewed",
                    "renewed_at": datetime.now().isoformat(),
                    "new_period_end": (datetime.now() + timedelta(days=365)).isoformat()
                }
            
            elif '/cancel' in path:
                tenant_id = path.split('/')[-2]
                return {
                    "subscription_id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "status": "cancelled",
                    "canceled_at": datetime.now().isoformat(),
                    "cancellation_effective_date": (datetime.now() + timedelta(days=30)).isoformat()
                }
            
            elif '/process-renewals' in path:
                return {
                    "processed": 5,
                    "renewed": 4,
                    "failed": 1,
                    "timestamp": datetime.now().isoformat()
                }
        
        # ENTRY SERVICE (8218)
        elif self.service_port == 8218:
            if '/entry/v4/issue-code' in path:
                code = f"ENTRY-{uuid.uuid4().hex[:8].upper()}"
                ttl_minutes = body.get('ttl_minutes', 30)
                entry = {
                    "code_id": str(uuid.uuid4()),
                    "code": code,
                    "tenant_id": body.get('tenant_id', ''),
                    "user_id": body.get('user_id', ''),
                    "store_id": body.get('store_id'),
                    "provider": "internal",
                    "status": "active",
                    "ttl_minutes": ttl_minutes,
                    "expires_at": (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat(),
                    "qr_code_url": f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUg...",
                    "metadata": body.get('metadata', {}),
                    "created_at": datetime.now().isoformat()
                }
                self.storage['entry_codes'][code] = entry
                return {
                    "entry_code": code,
                    "code_id": entry["code_id"],
                    "tenant_id": entry["tenant_id"],
                    "user_id": entry["user_id"],
                    "expires_at": entry["expires_at"],
                    "ttl_minutes": ttl_minutes,
                    "qr_code": entry["qr_code_url"],
                    "status": "active"
                }
            
            elif '/entry/v4/validate-code' in path:
                code = body.get('code', '')
                entry = self.storage['entry_codes'].get(code)
                if entry:
                    is_valid = entry['status'] == 'active'
                    return {
                        "valid": is_valid,
                        "code": code,
                        "tenant_id": entry.get('tenant_id'),
                        "user_id": entry.get('user_id'),
                        "store_id": body.get('store_id'),
                        "validated_at": datetime.now().isoformat(),
                        "reason": None if is_valid else "Code expired or invalid"
                    }
                else:
                    return {
                        "valid": False,
                        "code": code,
                        "reason": "Code not found"
                    }
        
        # ENTITLEMENTS SERVICE (8223)
        elif self.service_port == 8223:
            if '/entitlements/v2/usage/record' in path:
                return {
                    "recorded": True,
                    "tenant_id": body.get('tenant_id', ''),
                    "feature_code": body.get('feature_code', ''),
                    "quantity": body.get('quantity', 1),
                    "usage_timestamp": datetime.now().isoformat(),
                    "remaining_quota": 950,
                    "quota_reset_at": (datetime.now() + timedelta(days=30)).isoformat()
                }
            
            elif '/entitlements/v2/cache/clear' in path:
                return {
                    "status": "cleared",
                    "tenant_id": body.get('tenant_id', ''),
                    "cache_cleared_at": datetime.now().isoformat()
                }
        
        # IDENTITY SERVICE (8224)
        elif self.service_port == 8224:
            if path == '/identity/v4/users':
                user_id = str(uuid.uuid4())
                user = {
                    "id": user_id,
                    "tenant_id": body.get('tenant_id', ''),
                    "email": body.get('email', ''),
                    "name": body.get('display_name', ''),
                    "primary_cost_centre_id": body.get('primary_cost_centre_id'),
                    "user_metadata": body.get('metadata', {}),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['users'][user_id] = user
                return user
            
            elif path == '/identity/v4/roles':
                role_id = str(uuid.uuid4())
                role = {
                    "id": role_id,
                    "tenant_id": body.get('tenant_id', '550e8400-e29b-41d4-a716-446655440000'),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "permissions": body.get('permissions', []),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['roles'][role_id] = role
                return role
            
            elif path == '/identity/v4/role-assignments':
                return {
                    "id": str(uuid.uuid4()),
                    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
                    "user_id": body.get('user_id', ''),
                    "role_id": body.get('role_id', ''),
                    "assigned_at": datetime.now().isoformat(),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
            
            elif path == '/identity/v4/token':
                return {
                    "token": f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.{uuid.uuid4().hex}.{uuid.uuid4().hex[:16]}",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "user_id": body.get('user_id', ''),
                    "scopes": body.get('scopes', [])
                }
            
            elif '/oauth/providers' in path:
                return {
                    "provider_id": str(uuid.uuid4()),
                    "provider": body.get('provider', 'google'),
                    "client_id": body.get('client_id', ''),
                    "status": "configured",
                    "created_at": datetime.now().isoformat()
                }
            
            elif '/oauth/initiate' in path:
                return {
                    "provider": body.get('provider', 'google'),
                    "authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?client_id=xxx&state={uuid.uuid4().hex}",
                    "state": uuid.uuid4().hex,
                    "redirect_uri": "http://localhost:8224/identity/v4/oauth/callback"
                }
            
            elif '/oauth/callback' in path:
                return {
                    "user_id": str(uuid.uuid4()),
                    "email": "oauth.user@example.com",
                    "name": "OAuth User",
                    "provider": body.get('provider', 'google'),
                    "token": f"eyJ...{uuid.uuid4().hex}",
                    "authenticated_at": datetime.now().isoformat()
                }
        
        # Default POST response
        return {
            "status": "created",
            "id": str(uuid.uuid4()),
            "created_at": datetime.now().isoformat()
        }
    
    def handle_put_request(self, path, body):
        """Handle PUT requests"""
        
        # PROVISIONING SERVICE (8000)
        if self.service_port == 8000:
            if '/provisioning/sites/' in path:
                site_id = path.split('/')[-1].split('?')[0]
                site = {
                    "site_id": site_id,
                    "tenant_id": body.get('tenant_id', '550e8400-e29b-41d4-a716-446655440000'),
                    "name": body.get('name', ''),
                    "site_type": body.get('site_type', 'office'),
                    "geo": body.get('geo'),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
                self.storage['sites'][site_id] = site
                return site
            
            elif '/provisioning/stores/' in path:
                store_id = path.split('/')[-1].split('?')[0]
                store = {
                    "store_id": store_id,
                    "site_id": body.get('site_id', ''),
                    "name": body.get('name', ''),
                    "store_type": body.get('store_type', 'retail'),
                    "geo": body.get('geo'),
                    "created_at": datetime.now().isoformat()
                }
                self.storage['stores'][store_id] = store
                return store
            
            elif '/provisioning/users/' in path:
                user_id = path.split('/')[-1]
                api_key = f"zq_key_{hashlib.md5(user_id.encode()).hexdigest()[:16]}" if body.get('generate_api_key') else None
                user = {
                    "user_id": user_id,
                    "tenant_id": body.get('tenant_id', ''),
                    "email": body.get('email', ''),
                    "display_name": body.get('display_name', ''),
                    "active": True,
                    "api_key": api_key,
                    "api_key_created_at": datetime.now().isoformat() if api_key else None,
                    "permissions": body.get('permissions', []),
                    "created_at": datetime.now().isoformat()
                }
                self.storage['users'][user_id] = user
                return user
            
            elif '/provisioning/roles/' in path:
                role_id = path.split('/')[-1]
                role = {
                    "role_id": role_id,
                    "code": body.get('code', ''),
                    "name": body.get('name', ''),
                    "description": body.get('description'),
                    "created_at": datetime.now().isoformat()
                }
                self.storage['roles'][role_id] = role
                return role
            
            elif '/provisioning/vendors/' in path:
                vendor_id = path.split('/')[-1]
                vendor = {
                    "vendor_id": vendor_id,
                    "tenant_id": body.get('tenant_id', ''),
                    "name": body.get('name', ''),
                    "contact_email": body.get('contact_email'),
                    "description": body.get('description'),
                    "status": "active",
                    "created_at": datetime.now().isoformat()
                }
                self.storage['vendors'][vendor_id] = vendor
                return vendor
        
        # ORDERS SERVICE (8002)
        elif self.service_port == 8002:
            if '/orders/' in path:
                order_id = path.split('/')[-1]
                order = self.storage['orders'].get(order_id, {})
                order.update({
                    "order_id": order_id,
                    "fulfillment_status": body.get('fulfillment_status', 'completed'),
                    "order_status": body.get('order_status', order.get('order_status', 'pending')),
                    "updated_at": datetime.now().isoformat()
                })
                self.storage['orders'][order_id] = order
                return order
        
        # SUBSCRIPTIONS SERVICE (8212)
        elif self.service_port == 8212:
            if '/plans/' in path and '/features/' in path:
                plan_code = path.split('/')[4]
                feature_code = path.split('/')[-1]
                return {
                    "status": "added",
                    "plan_code": plan_code,
                    "feature_code": feature_code,
                    "enabled": True,
                    "limits": body.get('limits', {}),
                    "added_at": datetime.now().isoformat()
                }
        
        # Default PUT
        return {
            "status": "updated",
            "id": path.split('/')[-1],
            "updated_at": datetime.now().isoformat()
        }
    
    def log_message(self, format, *args):
        pass  # Suppress default logs

def create_handler(service_name, port):
    class CustomHandler(RealisticMockHandler):
        pass
    CustomHandler.service_name = service_name
    CustomHandler.service_port = port
    return CustomHandler

def start_server(port, service_name):
    handler = create_handler(service_name, port)
    server = HTTPServer(('localhost', port), handler)
    print(f"✓ {service_name:30s} → Port {port}")
    server.serve_forever()

# Core 8 services matching ZeroQue_Services.json
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
    print()
    print("=" * 70)
    print("🚀 ZeroQue Core 8 Services - REALISTIC DATABASE SCHEMA")
    print("=" * 70)
    print()
    print("All responses match REAL database models from main.py files:")
    print("  • Full field coverage (all columns)")
    print("  • Proper data types (UUIDs, timestamps, etc.)")
    print("  • Realistic defaults and metadata")
    print("  • In-memory storage (persists during session)")
    print()
    
    threads = []
    for port, name in services:
        thread = threading.Thread(target=start_server, args=(port, name), daemon=True)
        thread.start()
        threads.append(thread)
    
    print()
    print("=" * 70)
    print("✅ ALL 8 SERVICES RUNNING WITH REAL DATABASE SCHEMA!")
    print("=" * 70)
    print()
    print("Examples:")
    print("  POST /provisioning/tenants  → Full Tenant object with all fields")
    print("  GET  /products              → Product list with SKU, barcode, etc.")
    print("  POST /orders                → Order with items, totals, timestamps")
    print()
    print("Ready for Postman testing!")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping all services...")
        print("✓ Services stopped")

