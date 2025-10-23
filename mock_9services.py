#!/usr/bin/env python3
"""Mock 9 Services - Including CV Gateway with Device Monitoring"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, threading, uuid, hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

class Handler(BaseHTTPRequestHandler):
    service_name, service_port = "Unknown", 8000
    storage = {'tenants':{}, 'sites':{}, 'stores':{}, 'users':{}, 'roles':{}, 'vendors':{}, 
               'cost_centres':{}, 'products':{}, 'orders':{}, 'pricebooks':{}, 'subscriptions':{}, 
               'plans':{}, 'features':{}, 'entry_codes':{}, 'devices':{}}
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        if path == '/health':
            return self.send_json(200, {"status":"healthy", "service":self.service_name, "version":"4.1.0", "timestamp":datetime.now().isoformat()})
        if path == '/metrics':
            return self.send_json(200, {"service":self.service_name, "uptime_seconds":3600, "requests_total":1234})
        if path in ['/readiness', '/']:
            return self.send_json(200, {"ready":True, "service":self.service_name})
        
        self.send_json(200, self.get_response(path, query))
    
    def do_POST(self): self.send_json(201, self.post_response(self.path, self.read_body()))
    def do_PUT(self): self.send_json(200, self.put_response(self.path, self.read_body()))
    def do_DELETE(self): self.send_json(200, {"status":"deleted"})
    
    def read_body(self):
        try:
            cl = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
        except: return {}
    
    def send_json(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())
    
    def get_response(self, path, query):
        # PROVISIONING (8000)
        if self.service_port == 8000:
            if '/tenants' in path: return {"tenants":list(self.storage['tenants'].values()), "total":len(self.storage['tenants'])}
            if '/sites' in path: return {"sites":list(self.storage['sites'].values()), "total":len(self.storage['sites'])}
            if '/stores' in path: return {"stores":list(self.storage['stores'].values()), "total":len(self.storage['stores'])}
            if '/users' in path: return {"users":list(self.storage['users'].values()), "total":len(self.storage['users'])}
            if '/roles' in path: return {"roles":list(self.storage['roles'].values()), "total":len(self.storage['roles'])}
            if '/vendors' in path: return {"vendors":list(self.storage['vendors'].values()), "total":len(self.storage['vendors'])}
            if '/cost-centres' in path: return {"cost_centres":list(self.storage['cost_centres'].values()), "total":len(self.storage['cost_centres'])}
        
        # CATALOG (8001)
        elif self.service_port == 8001:
            if path == '/products': return {"products":list(self.storage['products'].values()), "total":len(self.storage['products']), "page":1}
            if '/products/' in path and path.count('/') == 2: return self.storage['products'].get(path.split('/')[-1], {"error":"Not found"})
            if '/categories' in path: return {"categories":[], "total":0}
            if '/bundles' in path and path.count('/') == 2: return {"bundles":[], "total":0}
            if '/bundles/' in path: return self.storage.get('bundles', {}).get(path.split('/')[-1], {"error":"Not found"})
        
        # ORDERS (8002)
        elif self.service_port == 8002:
            if path == '/orders': return {"orders":list(self.storage['orders'].values()), "total":len(self.storage['orders'])}
            if '/orders/' in path: return self.storage['orders'].get(path.split('/')[-1], {"error":"Not found"})
        
        # PRICING (8006)
        elif self.service_port == 8006:
            if '/pricebooks' in path: return {"pricebooks":list(self.storage['pricebooks'].values()), "total":len(self.storage['pricebooks'])}
        
        # CV GATEWAY (8080) - DEVICE MONITORING
        elif self.service_port == 8080:
            if path == '/devices/status':
                tenant_id = query.get('tenant_id', [''])[0]
                devices = [
                    {"device_id":"DEV-CAM-001", "tenant_id":tenant_id, "site_id":str(uuid.uuid4()), "device_type":"camera", 
                     "device_name":"Front Entrance Camera", "zone":"entrance", "status":"online", "health_score":95, 
                     "last_heartbeat":datetime.now().isoformat(), "device_metadata":{"firmware":"v1.2.3","ip":"192.168.1.100"}, 
                     "created_at":datetime.now().isoformat(), "updated_at":None},
                    {"device_id":"DEV-SENSOR-002", "tenant_id":tenant_id, "site_id":str(uuid.uuid4()), "device_type":"sensor", 
                     "device_name":"Inventory Sensor #2", "zone":"warehouse", "status":"online", "health_score":88, 
                     "last_heartbeat":datetime.now().isoformat(), "device_metadata":{"battery":"85%"}, 
                     "created_at":datetime.now().isoformat(), "updated_at":None}
                ]
                return {"devices":devices, "total":2, "tenant_id":tenant_id}
            
            if '/devices/' in path and '/status' in path:
                device_id = path.split('/')[2]
                return {
                    "device_id":device_id, "tenant_id":"550e8400-e29b-41d4-a716-446655440000", "site_id":str(uuid.uuid4()),
                    "device_type":"camera", "device_name":f"Device {device_id}", "zone":"zone1", "status":"online", 
                    "health_score":92, "last_heartbeat":datetime.now().isoformat(), "device_metadata":{"firmware":"v1.0"},
                    "recent_logs":[{"id":str(uuid.uuid4()), "status":"online", "health_score":92, "created_at":datetime.now().isoformat()}],
                    "created_at":datetime.now().isoformat(), "updated_at":None
                }
            
            if '/cv/reviews' in path: return {"reviews":[], "total":0}
            if '/cv/orders' in path: return {"orders":[], "total":0}
            if '/cv/stats/' in path:
                tenant_id = path.split('/')[-1]
                return {"tenant_id":tenant_id, "total_orders":45, "total_revenue_minor":125000, "avg_basket_size_minor":2777, 
                        "active_devices":12, "stats_period":"last_30_days"}
        
        # SUBSCRIPTIONS (8212)
        elif self.service_port == 8212:
            if path == '/subscriptions/v2/plans':
                return {"plans":[{"id":1, "code":"core", "name":"Core Plan", "price_yearly_minor":99900, "currency":"GBP", "active":True}], "total":1}
            if '/features' in path and 'plans' in path:
                return {"features":[{"code":"sku_management", "name":"SKU Management", "enabled":True, "rate_limit":1000}], "total":1}
            if '/subscriptions/' in path:
                tid = path.split('/')[-1]
                return {"subscription_id":str(uuid.uuid4()), "tenant_id":tid, "plan_code":"core", "status":"active", 
                        "current_period_start":datetime.now().isoformat(), "current_period_end":(datetime.now()+timedelta(days=365)).isoformat()}
        
        # ENTRY (8218)
        elif self.service_port == 8218:
            if '/entry/v4/codes' in path: return {"codes":list(self.storage['entry_codes'].values()), "total":len(self.storage['entry_codes'])}
            if '/entry/v4/status/' in path:
                code = path.split('/')[-1]
                return self.storage['entry_codes'].get(code, {"code":code, "status":"not_found"})
        
        # ENTITLEMENTS (8223)
        elif self.service_port == 8223:
            if '/check' in path:
                return {"entitled":True, "feature_code":"advanced_analytics", "tenant_id":"550e8400-e29b-41d4-a716-446655440000", 
                        "plan_code":"core", "rate_limit":1000, "remaining_quota":950, "checked_at":datetime.now().isoformat()}
            if '/usage/' in path:
                return {"tenant_id":path.split('/')[-1], "usage":[{"feature_code":"api_calls", "used":150, "limit":1000}], "total":1}
        
        # IDENTITY (8224)
        elif self.service_port == 8224:
            if '/users' in path: return {"users":list(self.storage['users'].values()), "total":len(self.storage['users'])}
            if '/roles' in path and 'assignments' not in path: return {"roles":list(self.storage['roles'].values()) or [{"id":str(uuid.uuid4()), "name":"Admin", "permissions":["*"]}], "total":max(1, len(self.storage['roles']))}
            if '/reports' in path: return {"total_users":len(self.storage['users']), "active_users":len(self.storage['users']), "total_roles":len(self.storage['roles'])}
            if '/oauth/providers' in path: return {"providers":[], "total":0}
        
        return {"message":"Endpoint not mocked", "path":path}
    
    def post_response(self, path, body):
        # PROVISIONING (8000)
        if self.service_port == 8000:
            if '/tenants' in path:
                tid = str(uuid.uuid4())
                t = {"tenant_id":tid, "name":body.get('name',''), "type":body.get('tenant_type','customer'), "active":True, 
                     "tenant_metadata":body.get('metadata',{}), "created_at":datetime.now().isoformat(), "updated_at":None}
                self.storage['tenants'][tid] = t
                return t
            if '/cost-centres' in path:
                cid = f"cc_{uuid.uuid4().hex[:12]}"
                return {"cost_centre_id":cid, "tenant_id":body.get('tenant_id',''), "name":body.get('name',''), 
                        "budget_minor":body.get('budget_minor',0), "spent_minor":0, "currency_code":"GBP", "status":"active", "created_at":datetime.now().isoformat()}
            if '/users/bulk-import' in path:
                imported = []
                for u in body.get('users', []):
                    uid = str(uuid.uuid4())
                    user = {"user_id":uid, "tenant_id":body.get('tenant_id',''), "email":u.get('email',''), "display_name":u.get('display_name',''), 
                            "active":True, "api_key":f"zq_key_{hashlib.md5(uid.encode()).hexdigest()[:16]}" if body.get('auto_generate_api_keys') else None,
                            "api_key_created_at":datetime.now().isoformat() if body.get('auto_generate_api_keys') else None,
                            "permissions":u.get('permissions',[]), "created_at":datetime.now().isoformat()}
                    self.storage['users'][uid] = user
                    imported.append(user)
                return {"imported_count":len(imported), "failed_count":0, "users":imported}
        
        # CATALOG (8001)
        elif self.service_port == 8001:
            if path == '/products':
                pid = str(uuid.uuid4())
                p = {"product_id":pid, "tenant_id":body.get('tenant_id','550e8400-e29b-41d4-a716-446655440000'), "vendor_id":body.get('vendor_id',''),
                     "name":body.get('name',''), "description":body.get('description'), "sku":body.get('sku',''), "barcode":body.get('barcode'),
                     "category_id":body.get('category_id'), "brand":body.get('brand'), "base_price_minor":body.get('base_price_minor',0),
                     "currency":body.get('currency','GBP'), "weight_grams":body.get('weight_grams'), "dimensions_cm":body.get('dimensions_cm'),
                     "is_active":True, "metadata_json":body.get('metadata',{}), "created_at":datetime.now().isoformat(), "updated_at":None}
                self.storage['products'][pid] = p
                return p
            if '/variants' in path:
                return {"variant_id":str(uuid.uuid4()), "product_id":path.split('/')[2], "name":body.get('name',''), "sku":body.get('sku',''),
                        "price_adjustment_minor":body.get('price_adjustment_minor',0), "attributes":body.get('attributes',{}), "is_active":True}
            if '/categories' in path:
                return {"category_id":str(uuid.uuid4()), "name":body.get('name',''), "description":body.get('description'), "created_at":datetime.now().isoformat()}
            if '/bundles' in path:
                return {"bundle_id":str(uuid.uuid4()), "name":body.get('name',''), "bundle_sku":body.get('bundle_sku',''), 
                        "bundle_type":body.get('bundle_type','bundle'), "base_price_minor":body.get('base_price_minor',0), "components":body.get('components',[])}
            if '/search' in path:
                return {"results":[{"product_id":str(uuid.uuid4()), "name":"Search Result", "sku":"SEARCH-001", "base_price_minor":1999, "relevance_score":0.95}], "total":1}
        
        # ORDERS (8002)
        elif self.service_port == 8002:
            if '/orders' in path:
                oid, onum = str(uuid.uuid4()), f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                items = body.get('items',[])
                o = {"order_id":oid, "tenant_id":body.get('tenant_id',''), "site_id":body.get('site_id'), "store_id":body.get('store_id'),
                     "customer_id":body.get('customer_id',''), "order_number":onum, "order_status":"pending", "order_type":body.get('order_type','retail'),
                     "total_amount_minor":sum(i.get('unit_price_minor',0)*i.get('quantity',1) for i in items), "currency":"GBP",
                     "payment_status":"pending", "fulfillment_status":"pending", "items":[
                        {"item_id":str(uuid.uuid4()), "order_id":oid, "product_id":i.get('product_id',''), "quantity":i.get('quantity',1),
                         "unit_price_minor":i.get('unit_price_minor',0), "total_minor":i.get('unit_price_minor',0)*i.get('quantity',1)} for i in items
                     ], "created_at":datetime.now().isoformat(), "updated_at":None}
                self.storage['orders'][oid] = o
                return o
        
        # PRICING (8006)
        elif self.service_port == 8006:
            if path == '/pricebooks':
                pbid = str(uuid.uuid4())
                pb = {"pricebook_id":pbid, "tenant_id":body.get('tenant_id','550e8400-e29b-41d4-a716-446655440000'), "name":body.get('name',''),
                      "description":body.get('description'), "currency":body.get('currency','GBP'), "is_active":True, 
                      "custom_metadata":body.get('metadata',{}), "created_at":datetime.now().isoformat(), "updated_at":None}
                self.storage['pricebooks'][pbid] = pb
                return pb
            if '/rules' in path:
                return {"rule_id":str(uuid.uuid4()), "pricebook_id":body.get('pricebook_id',''), "product_id":body.get('product_id'),
                        "rule_type":body.get('rule_type','fixed'), "rule_value":body.get('rule_value',0.0), "is_active":True, "created_at":datetime.now().isoformat()}
            if '/calculate' in path:
                base = body.get('base_price_minor',0)
                return {"product_id":body.get('product_id',''), "quantity":body.get('quantity',1), "base_price_minor":base,
                        "discount_minor":int(base*0.05), "final_price_minor":int(base*0.95), "currency":"GBP", "calculated_at":datetime.now().isoformat()}
        
        # CV GATEWAY (8080) - DEVICE MONITORING
        elif self.service_port == 8080:
            if path == '/cv/webhook/order':
                oid = str(uuid.uuid4())
                return {"order_id":oid, "store_id":body.get('store_id',''), "status":"created", "items":body.get('items',[]), 
                        "total_amount_minor":0, "currency":"GBP", "created_at":datetime.now().isoformat()}
            if '/devices/' in path and '/alert' in path:
                device_id = path.split('/')[2]
                aid = str(uuid.uuid4())
                alert = {"id":aid, "device_id":device_id, "tenant_id":"550e8400-e29b-41d4-a716-446655440000", 
                         "alert_type":body.get('alert_type','error'), "severity":body.get('severity','warning'), "message":body.get('message',''),
                         "status":"open", "acknowledged_by":None, "acknowledged_at":None, "resolved_at":None, "created_at":datetime.now().isoformat()}
                return alert
            if '/cv/reviews/' in path and '/resolve' in path:
                review_id = path.split('/')[3]
                return {"review_id":review_id, "status":"resolved", "resolution":body.get('resolution','approved'), "resolved_at":datetime.now().isoformat()}
        
        # SUBSCRIPTIONS (8212)
        elif self.service_port == 8212:
            if path == '/subscriptions/v2/features':
                return {"feature_id":str(uuid.uuid4()), "code":body.get('code',''), "name":body.get('name',''), "active":True, "created_at":datetime.now().isoformat()}
            if path == '/subscriptions/v2/plans':
                return {"id":1, "code":body.get('code',''), "name":body.get('name',''), "price_yearly_minor":body.get('price_yearly_minor',0), 
                        "currency":"GBP", "active":True, "created_at":datetime.now().isoformat()}
            if path == '/subscriptions/v2/subscriptions':
                return {"subscription_id":str(uuid.uuid4()), "tenant_id":body.get('tenant_id',''), "plan_code":body.get('plan_code','core'),
                        "status":"active", "billing_cycle":body.get('billing_cycle','yearly'), "auto_renew":body.get('auto_renew',True),
                        "current_period_start":datetime.now().isoformat(), "current_period_end":(datetime.now()+timedelta(days=365)).isoformat()}
            if '/renew' in path:
                return {"subscription_id":str(uuid.uuid4()), "status":"renewed", "renewed_at":datetime.now().isoformat()}
            if '/cancel' in path:
                return {"subscription_id":str(uuid.uuid4()), "status":"cancelled", "canceled_at":datetime.now().isoformat()}
        
        # ENTRY (8218)
        elif self.service_port == 8218:
            if '/issue-code' in path:
                code = f"ENTRY-{uuid.uuid4().hex[:8].upper()}"
                ttl = body.get('ttl_minutes',30)
                e = {"code_id":str(uuid.uuid4()), "code":code, "tenant_id":body.get('tenant_id',''), "user_id":body.get('user_id',''),
                     "store_id":body.get('store_id'), "provider":"internal", "status":"active", "ttl_minutes":ttl,
                     "expires_at":(datetime.now()+timedelta(minutes=ttl)).isoformat(), "qr_code":"data:image/png;base64,iVBORw0KG...",
                     "metadata":body.get('metadata',{}), "created_at":datetime.now().isoformat()}
                self.storage['entry_codes'][code] = e
                return {"entry_code":code, "code_id":e["code_id"], "expires_at":e["expires_at"], "ttl_minutes":ttl, "qr_code":e["qr_code"]}
            if '/validate-code' in path:
                code = body.get('code','')
                e = self.storage['entry_codes'].get(code)
                return {"valid":bool(e), "code":code, "tenant_id":e.get('tenant_id') if e else None, "user_id":e.get('user_id') if e else None,
                        "validated_at":datetime.now().isoformat(), "reason":None if e else "Code not found"}
        
        # ENTITLEMENTS (8223)
        elif self.service_port == 8223:
            if '/usage/record' in path:
                return {"recorded":True, "tenant_id":body.get('tenant_id',''), "feature_code":body.get('feature_code',''), 
                        "quantity":body.get('quantity',1), "remaining_quota":950, "usage_timestamp":datetime.now().isoformat()}
            if '/cache/clear' in path:
                return {"status":"cleared", "tenant_id":body.get('tenant_id',''), "cache_cleared_at":datetime.now().isoformat()}
        
        # IDENTITY (8224)
        elif self.service_port == 8224:
            if '/users' in path:
                uid = str(uuid.uuid4())
                u = {"id":uid, "tenant_id":body.get('tenant_id',''), "email":body.get('email',''), "name":body.get('display_name',''),
                     "user_metadata":body.get('metadata',{}), "created_at":datetime.now().isoformat(), "updated_at":None}
                self.storage['users'][uid] = u
                return u
            if '/roles' in path and 'assignments' not in path:
                rid = str(uuid.uuid4())
                r = {"id":rid, "tenant_id":body.get('tenant_id','550e8400-e29b-41d4-a716-446655440000'), "name":body.get('name',''),
                     "permissions":body.get('permissions',[]), "created_at":datetime.now().isoformat()}
                self.storage['roles'][rid] = r
                return r
            if '/role-assignments' in path:
                return {"id":str(uuid.uuid4()), "user_id":body.get('user_id',''), "role_id":body.get('role_id',''), 
                        "assigned_at":datetime.now().isoformat()}
            if '/token' in path:
                return {"token":f"eyJ.{uuid.uuid4().hex}.{uuid.uuid4().hex[:16]}", "token_type":"Bearer", "expires_in":3600, 
                        "expires_at":(datetime.now()+timedelta(hours=1)).isoformat(), "scopes":body.get('scopes',[])}
            if '/oauth/providers' in path:
                return {
                    "id": str(uuid.uuid4()),
                    "tenant_id": body.get('tenant_id', ''),
                    "provider_type": body.get('provider_type', 'google'),
                    "provider_name": body.get('provider_name', 'Google OAuth'),
                    "client_id": body.get('client_id', ''),
                    "enabled": True,
                    "scopes": body.get('scopes', ['openid', 'profile', 'email']),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": None
                }
            if '/oauth/initiate' in path:
                return {
                    "authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?client_id={body.get('provider_id', '')}&state={uuid.uuid4().hex}",
                    "state": uuid.uuid4().hex,
                    "provider_id": body.get('provider_id', ''),
                    "redirect_uri": body.get('redirect_uri', ''),
                    "initiated_at": datetime.now().isoformat()
                }
            if '/oauth/callback' in path:
                return {
                    "user_id": str(uuid.uuid4()),
                    "email": "oauth.user@example.com",
                    "name": "OAuth User",
                    "token": f"eyJ.{uuid.uuid4().hex}.{uuid.uuid4().hex[:16]}",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "state": body.get('state', ''),
                    "authenticated_at": datetime.now().isoformat()
                }
        
        return {"status":"created", "id":str(uuid.uuid4()), "created_at":datetime.now().isoformat()}
    
    def put_response(self, path, body):
        # PROVISIONING (8000)
        if self.service_port == 8000:
            if '/sites/' in path:
                sid = path.split('/')[3].split('?')[0]
                s = {"site_id":sid, "tenant_id":body.get('tenant_id','550e8400-e29b-41d4-a716-446655440000'), "name":body.get('name',''),
                     "site_type":body.get('site_type','office'), "geo":body.get('geo'), "device_metadata":body.get('device_metadata',{}),
                     "created_at":datetime.now().isoformat(), "updated_at":None}
                self.storage['sites'][sid] = s
                return s
            if '/stores/' in path:
                stid = path.split('/')[3].split('?')[0]
                st = {"store_id":stid, "site_id":body.get('site_id',''), "name":body.get('name',''), "store_type":body.get('store_type','retail'),
                      "geo":body.get('geo'), "created_at":datetime.now().isoformat()}
                self.storage['stores'][stid] = st
                return st
            if '/users/' in path:
                uid = path.split('/')[3]
                api_key = f"zq_key_{hashlib.md5(uid.encode()).hexdigest()[:16]}" if body.get('generate_api_key') else None
                u = {"user_id":uid, "tenant_id":body.get('tenant_id',''), "email":body.get('email',''), "display_name":body.get('display_name',''),
                     "active":True, "api_key":api_key, "api_key_created_at":datetime.now().isoformat() if api_key else None,
                     "permissions":body.get('permissions',[]), "created_at":datetime.now().isoformat()}
                self.storage['users'][uid] = u
                return u
            if '/roles/' in path:
                rid = path.split('/')[3]
                r = {"role_id":rid, "code":body.get('code',''), "name":body.get('name',''), "description":body.get('description'), "created_at":datetime.now().isoformat()}
                self.storage['roles'][rid] = r
                return r
            if '/vendors/' in path:
                vid = path.split('/')[3]
                v = {"vendor_id":vid, "tenant_id":body.get('tenant_id',''), "name":body.get('name',''), "contact_email":body.get('contact_email'),
                     "description":body.get('description'), "status":"active", "created_at":datetime.now().isoformat()}
                self.storage['vendors'][vid] = v
                return v
        
        # CV GATEWAY (8080) - UPDATE DEVICE STATUS
        elif self.service_port == 8080:
            if '/devices/' in path and '/status' in path:
                device_id = path.split('/')[2]
                return {"device_id":device_id, "status":body.get('status','online'), "health_score":body.get('health_score',100),
                        "last_heartbeat":datetime.now().isoformat(), "updated_at":datetime.now().isoformat()}
        
        # ORDERS (8002)
        elif self.service_port == 8002:
            if '/orders/' in path:
                oid = path.split('/')[2]
                o = self.storage['orders'].get(oid, {})
                o.update({"order_id":oid, "fulfillment_status":body.get('fulfillment_status','completed'), "updated_at":datetime.now().isoformat()})
                self.storage['orders'][oid] = o
                return o
        
        # SUBSCRIPTIONS (8212)
        elif self.service_port == 8212:
            if '/plans/' in path and '/features/' in path:
                plan_code, feature_code = path.split('/')[4], path.split('/')[-1]
                return {"status":"added", "plan_code":plan_code, "feature_code":feature_code, "enabled":True, "added_at":datetime.now().isoformat()}
        
        return {"status":"updated", "id":path.split('/')[-1], "updated_at":datetime.now().isoformat()}
    
    def log_message(self, fmt, *args): pass

def create_handler(name, port):
    class H(Handler): pass
    H.service_name, H.service_port = name, port
    return H

def start(port, name):
    HTTPServer(('localhost', port), create_handler(name, port)).serve_forever()

if __name__ == "__main__":
    services = [(8000,"Provisioning"), (8001,"Catalog"), (8002,"Orders"), (8006,"Pricing"),
                (8080,"CV Gateway"), (8212,"Subscriptions"), (8218,"Entry"), (8223,"Entitlements"), (8224,"Identity")]
    
    print("\n" + "="*70)
    print("🚀 ZeroQue 9 Services - With CV Gateway Device Monitoring")
    print("="*70 + "\n")
    
    threads = []
    for port, name in services:
        t = threading.Thread(target=start, args=(port, name), daemon=True)
        t.start()
        threads.append(t)
        print(f"✓ {name:20s} → Port {port}")
    
    print("\n" + "="*70)
    print("✅ ALL 9 SERVICES RUNNING (Including CV Gateway Device Monitoring)")
    print("="*70 + "\n")
    print("Device endpoints available:")
    print("  GET  /devices/status              - List all devices")
    print("  GET  /devices/{id}/status         - Get device details")
    print("  PUT  /devices/{id}/status         - Update device status")
    print("  POST /devices/{id}/alert          - Create device alert")
    print("\nPress Ctrl+C to stop\n")
    
    try:
        for t in threads: t.join()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping...")

