"""
ZeroQue V2 - Multi-Tenant Marketplace E2E Demo
Streamlit application for testing the complete V2 architecture
"""

import os
import json
import random
import string
import csv
import io
import uuid
import requests
import streamlit as st
from datetime import datetime
from typing import Dict, List, Any

# -------------------- Config --------------------
# V2 Service URLs
PROVISIONING_BASE = os.getenv("PROVISIONING_BASE", "http://localhost:8201")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8203")
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8209")

# Service status
SERVICES = {
    "Provisioning": PROVISIONING_BASE,
    "Orders": ORDERS_BASE,
    "Pricing": PRICING_BASE,
}

# -------------------- Helpers --------------------
def generate_uuid() -> str:
    """Generate a UUID for V2 architecture"""
    return str(uuid.uuid4())

def rid(prefix: str) -> str:
    """Generate a random ID with prefix"""
    return f"{prefix}-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

def api_call(method: str, url: str, payload: dict = None, params: dict = None):
    """Make API call with error handling"""
    try:
        if method.upper() == "GET":
            r = requests.get(url, params=params, timeout=20)
        elif method.upper() == "POST":
            r = requests.post(url, json=payload, timeout=20)
        elif method.upper() == "PUT":
            r = requests.put(url, json=payload, timeout=20)
        else:
            return 0, {"error": f"Unsupported method: {method}"}
        
        return r.status_code, _safe_json(r)
    except Exception as e:
        return 0, {"error": str(e)}

def _safe_json(r: requests.Response):
    """Safely parse JSON response"""
    try:
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return {"status": r.status_code, "text": r.text}
    except Exception:
        return {"status": r.status_code, "text": r.text}

def show_response(status_code: int, response: dict, title: str = "Response"):
    """Display API response with formatting"""
    if status_code >= 200 and status_code < 300:
        st.success(f"✅ {title} - Status: {status_code}")
    else:
        st.error(f"❌ {title} - Status: {status_code}")
    
    with st.expander("Response Details", expanded=False):
        st.json(response)

def show_curl(title: str, method: str, url: str, payload: dict = None):
    """Show curl command for API call"""
    with st.expander(f"🔧 {title} - cURL", expanded=False):
        if payload:
            cmd = f"""curl -X {method.upper()} "{url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload, indent=2)}'"""
        else:
            cmd = f'curl -X {method.upper()} "{url}"'
        st.code(cmd, language="bash")

# -------------------- Session State --------------------
defaults = {
    # Tenant Management
    "tenant_id": "",
    "tenant_name": "ZeroQue Marketplace",
    "tenant_type": "marketplace",
    "scenario_id": "",
    
    # Site Management
    "site_id": "",
    "site_name": "London Warehouse",
    "site_type": "warehouse",
    "site_address": "123 Main St, London, UK",
    "site_geo_lat": 51.5074,
    "site_geo_lng": -0.1278,
    
    # Store Management
    "store_id": "",
    "store_name": "London Store",
    "store_type": "cashierless",
    "store_address": "456 High St, London, UK",
    "store_geo_lat": 51.5074,
    "store_geo_lng": -0.1278,
    
    # User Management
    "user_id": "",
    "user_email": "admin@zeroque.com",
    "user_display_name": "Admin User",
    "user_active": True,
    
    # Vendor Management
    "vendor_id": "",
    "vendor_name": "Premium Vendors Ltd",
    "vendor_description": "Premium product supplier",
    "vendor_rating": 4.5,
    
    # Product Management
    "product_master_id": "",
    "product_name": "Premium Coffee",
    "product_description": "High-quality coffee beans",
    "product_variant_id": "",
    "variant_name": "Medium Roast",
    "variant_sku": "COFFEE-MED-001",
    
    # Pricing
    "pricebook_id": "",
    "pricebook_name": "Standard Pricing",
    "price_minor": 299,
    "currency": "GBP",
    
    # Orders
    "order_id": "",
    "customer_id": "",
    "payment_method": "trade",
    "order_quantity": 2,
    
    # Vendor Offers
    "offer_id": "",
    "vendor_sku": "VND-COFFEE-001",
    "vendor_price_minor": 250,
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -------------------- Health Check --------------------
def check_service_health():
    """Check health of all V2 services"""
    health_status = {}
    for service_name, base_url in SERVICES.items():
        try:
            response = requests.get(f"{base_url}/health", timeout=5)
            if response.status_code == 200:
                health_status[service_name] = "✅ Healthy"
            else:
                health_status[service_name] = f"⚠️ Status: {response.status_code}"
        except Exception as e:
            health_status[service_name] = f"❌ Error: {str(e)[:50]}..."
    
    return health_status

# -------------------- UI --------------------
st.set_page_config(page_title="ZeroQue V2 E2E Demo", layout="wide")

# Header
st.title("🚀 ZeroQue V2 - Multi-Tenant Marketplace Demo")
st.markdown("""
**V2 Architecture Features:**
- Multi-tenant marketplace platform
- Advanced vendor management
- Sophisticated pricing engine with pricebooks
- Order processing with saga orchestration
- Complete tenant isolation with RLS
""")

# Service Health Status
with st.expander("🏥 Service Health Status", expanded=False):
    health_status = check_service_health()
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.write(f"**Provisioning** (Port 8201)")
        st.write(health_status.get("Provisioning", "❌ Unknown"))
    
    with col2:
        st.write(f"**Orders** (Port 8203)")
        st.write(health_status.get("Orders", "❌ Unknown"))
    
    with col3:
        st.write(f"**Pricing** (Port 8209)")
        st.write(health_status.get("Pricing", "❌ Unknown"))

# Main Tabs
tabs = st.tabs([
    "🏢 Tenant Management",
    "🏪 Site & Store Management", 
    "👥 User & Vendor Management",
    "📦 Product & Catalog Management",
    "💰 Pricing & Pricebooks",
    "🛒 Order Management",
    "📊 Browse & Reports"
])

# ===== Tenant Management =====
with tabs[0]:
    st.header("🏢 Tenant Management")
    st.markdown("Manage tenants in the multi-tenant marketplace")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create/Update Tenant")
        
        if st.button("🎲 Generate Tenant ID"):
            st.session_state.tenant_id = generate_uuid()
        
        st.text_input("Tenant ID", key="tenant_id", help="UUID for the tenant")
        st.text_input("Tenant Name", key="tenant_name")
        st.selectbox("Tenant Type", ["marketplace", "customer", "enterprise"], key="tenant_type")
        st.text_input("Scenario ID (Optional)", key="scenario_id")
        
        if st.button("💾 Create Tenant"):
            if st.session_state.tenant_name:
                # Use PUT with UUID for tenant creation
                tenant_id = st.session_state.tenant_id or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/v2/tenants/{tenant_id}"
                payload = {
                    "name": st.session_state.tenant_name,
                    "type": st.session_state.tenant_type,
                    "active": True
                }
                if st.session_state.scenario_id:
                    payload["scenario_id"] = st.session_state.scenario_id
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Tenant")
                show_curl("Create Tenant", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.tenant_id = tenant_id
            else:
                st.error("Please provide Tenant ID and Name")
    
    with col2:
        st.subheader("List Tenants")
        
        if st.button("📋 Fetch Tenants"):
            url = f"{PROVISIONING_BASE}/provisioning/v2/tenants"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} tenants")
                
                if response:
                    for tenant in response:
                        with st.expander(f"🏢 {tenant.get('name', 'Unknown')} - {tenant.get('tenant_id', 'No ID')}", expanded=False):
                            st.json(tenant)
                else:
                    st.info("No tenants found")
            else:
                show_response(status_code, response, "List Tenants")

# ===== Site & Store Management =====
with tabs[1]:
    st.header("🏪 Site & Store Management")
    st.markdown("Manage sites and stores in the marketplace")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Site Management")
        
        if st.button("🎲 Generate Site ID"):
            st.session_state.site_id = generate_uuid()
        
        st.text_input("Site ID", key="site_id")
        st.text_input("Site Name", key="site_name")
        st.selectbox("Site Type", ["warehouse", "distribution", "retail", "office"], key="site_type")
        st.text_input("Address", key="site_address")
        st.number_input("Latitude", key="site_geo_lat", format="%.6f")
        st.number_input("Longitude", key="site_geo_lng", format="%.6f")
        
        if st.button("💾 Create Site"):
            if st.session_state.site_name:
                # Use PUT with UUID for site creation
                site_id = st.session_state.site_id or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/v2/sites/{site_id}"
                payload = {
                    "name": st.session_state.site_name,
                    "site_type": st.session_state.site_type,
                    "address": st.session_state.site_address,
                    "geo_lat": st.session_state.site_geo_lat,
                    "geo_lng": st.session_state.site_geo_lng,
                    "timezone": "Europe/London",
                    "active": True
                }
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Site")
                show_curl("Create Site", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.site_id = site_id
        
        if st.button("📋 List Sites"):
            url = f"{PROVISIONING_BASE}/provisioning/v2/sites"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, "List Sites")
    
    with col2:
        st.subheader("Store Management")
        
        if st.button("🎲 Generate Store ID"):
            st.session_state.store_id = generate_uuid()
        
        st.text_input("Store ID", key="store_id")
        st.text_input("Store Name", key="store_name")
        st.selectbox("Store Type", ["cashierless", "traditional", "kiosk", "vending"], key="store_type")
        st.text_input("Store Address", key="store_address")
        st.number_input("Store Latitude", key="store_geo_lat", format="%.6f")
        st.number_input("Store Longitude", key="store_geo_lng", format="%.6f")
        
        if st.button("💾 Create Store"):
            if st.session_state.store_name:
                # Use PUT with UUID for store creation
                store_id = st.session_state.store_id or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/v2/stores/{store_id}"
                payload = {
                    "name": st.session_state.store_name,
                    "store_type": st.session_state.store_type,
                    "address": st.session_state.store_address,
                    "geo_lat": st.session_state.store_geo_lat,
                    "geo_lng": st.session_state.store_geo_lng,
                    "timezone": "Europe/London",
                    "active": True
                }
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Store")
                show_curl("Create Store", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.store_id = store_id
        
        if st.button("📋 List Stores"):
            url = f"{PROVISIONING_BASE}/provisioning/v2/stores"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, "List Stores")

# ===== User & Vendor Management =====
with tabs[2]:
    st.header("👥 User & Vendor Management")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("User Management")
        
        if st.button("🎲 Generate User ID"):
            st.session_state.user_id = generate_uuid()
        
        st.text_input("User ID", key="user_id")
        st.text_input("Email", key="user_email")
        st.text_input("Display Name", key="user_display_name")
        st.checkbox("Active", key="user_active")
        
        if st.button("👤 Create User"):
            if st.session_state.user_email:
                # Use PUT with UUID for user creation
                user_id = st.session_state.user_id or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/v2/users/{user_id}"
                payload = {
                    "email": st.session_state.user_email,
                    "display_name": st.session_state.user_display_name,
                    "active": st.session_state.user_active
                }
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create User")
                show_curl("Create User", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.user_id = user_id
        
        if st.button("📋 List Users"):
            url = f"{PROVISIONING_BASE}/provisioning/v2/users"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, "List Users")
    
    with col2:
        st.subheader("Vendor Management")
        
        if st.button("🎲 Generate Vendor ID"):
            st.session_state.vendor_id = generate_uuid()
        
        st.text_input("Vendor ID", key="vendor_id")
        st.text_input("Vendor Name", key="vendor_name")
        st.text_area("Description", key="vendor_description")
        st.number_input("Rating", key="vendor_rating", min_value=0.0, max_value=5.0, step=0.1)
        
        if st.button("🏪 Create Vendor"):
            if st.session_state.vendor_name:
                # Use PUT with UUID for vendor creation
                vendor_id = st.session_state.vendor_id or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/v2/vendors/{vendor_id}"
                payload = {
                    "name": st.session_state.vendor_name,
                    "description": st.session_state.vendor_description,
                    "rating": st.session_state.vendor_rating,
                    "active": True
                }
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Vendor")
                show_curl("Create Vendor", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.vendor_id = vendor_id
        
        if st.button("📋 List Vendors"):
            url = f"{PROVISIONING_BASE}/provisioning/v2/vendors"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, "List Vendors")

# ===== Product & Catalog Management =====
with tabs[3]:
    st.header("📦 Product & Catalog Management")
    st.markdown("This tab would integrate with a Catalog service (not yet implemented in V2)")
    
    st.info("""
    **Catalog Service Integration (Planned)**
    - Product Master management
    - Product Variants
    - Vendor Offers
    - Store Assortments
    - Product Media and Relationships
    """)
    
    # Placeholder for when catalog service is implemented
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Product Master")
        st.text_input("Product Name", key="product_name")
        st.text_area("Product Description", key="product_description")
        st.button("📦 Create Product (Coming Soon)", disabled=True)
    
    with col2:
        st.subheader("Vendor Offers")
        st.text_input("Vendor SKU", key="vendor_sku")
        st.number_input("Vendor Price (minor)", key="vendor_price_minor", min_value=0)
        st.button("🏷️ Create Offer (Coming Soon)", disabled=True)

# ===== Pricing & Pricebooks =====
with tabs[4]:
    st.header("💰 Pricing & Pricebooks")
    st.markdown("Advanced pricing engine with pricebooks and rules")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Pricebook Management")
        
        if st.button("🎲 Generate Pricebook ID"):
            st.session_state.pricebook_id = generate_uuid()
        
        st.text_input("Pricebook ID", key="pricebook_id")
        st.text_input("Pricebook Name", key="pricebook_name")
        st.selectbox("Currency", ["GBP", "USD", "EUR"], key="currency")
        
        if st.button("📋 Create Pricebook"):
            if st.session_state.pricebook_name:
                # Use PUT with UUID for pricebook creation
                pricebook_id = st.session_state.pricebook_id or generate_uuid()
                url = f"{PRICING_BASE}/pricing/v2/pricebooks/{pricebook_id}"
                payload = {
                    "name": st.session_state.pricebook_name,
                    "description": f"Pricebook for {st.session_state.pricebook_name}",
                    "pricebook_type": "standard",
                    "currency": st.session_state.currency,
                    "hierarchy_rank": 1,
                    "active": True
                }
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Pricebook")
                show_curl("Create Pricebook", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.pricebook_id = pricebook_id
        
        if st.button("📋 List Pricebooks"):
            url = f"{PRICING_BASE}/pricing/v2/pricebooks"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, "List Pricebooks")
    
    with col2:
        st.subheader("Price Resolution")
        
        st.text_input("Store ID for Pricing", value=st.session_state.store_id)
        st.text_input("Offer ID", key="offer_id")
        st.text_input("User ID for Pricing", value=st.session_state.user_id)
        st.number_input("Quantity", min_value=1, value=1, key="pricing_quantity")
        
        if st.button("💲 Resolve Price"):
            if st.session_state.offer_id and st.session_state.store_id:
                url = f"{PRICING_BASE}/pricing/v2/resolve"
                payload = {
                    "store_id": st.session_state.store_id,
                    "offer_id": st.session_state.offer_id,
                    "user_id": st.session_state.user_id,
                    "quantity": st.session_state.pricing_quantity,
                    "currency": st.session_state.currency
                }
                
                status_code, response = api_call("POST", url, payload)
                show_response(status_code, response, "Resolve Price")
                show_curl("Resolve Price", "POST", url, payload)
            else:
                st.error("Please provide Store ID and Offer ID")
        
        if st.button("📊 List Price Rules"):
            url = f"{PRICING_BASE}/pricing/v2/price-rules"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, "List Price Rules")

# ===== Order Management =====
with tabs[5]:
    st.header("🛒 Order Management")
    st.markdown("Order processing with saga orchestration and vendor splits")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Create Order")
        
        st.text_input("Tenant ID for Order", value=st.session_state.tenant_id)
        st.text_input("Store ID for Order", value=st.session_state.store_id)
        st.text_input("Customer ID", key="customer_id", value=st.session_state.user_id)
        st.selectbox("Payment Method", ["trade", "card", "cash"], key="payment_method")
        st.selectbox("Order Currency", ["GBP", "USD", "EUR"], index=0)
        
        # Order Items
        st.subheader("Order Items")
        st.text_input("Offer ID for Order", key="order_offer_id")
        st.number_input("Quantity", min_value=1, value=2, key="order_quantity")
        st.number_input("Unit Price (minor)", min_value=1, value=299, key="order_unit_price")
        
        if st.button("🛒 Create Order"):
            if (st.session_state.tenant_id and st.session_state.store_id and 
                st.session_state.customer_id and st.session_state.order_offer_id):
                
                total_minor = st.session_state.order_unit_price * st.session_state.order_quantity
                
                url = f"{ORDERS_BASE}/orders/v2"
                payload = {
                    "tenant_id": st.session_state.tenant_id,
                    "store_id": st.session_state.store_id,
                    "customer_id": st.session_state.customer_id,
                    "currency": st.session_state.currency,
                    "payment_method": st.session_state.payment_method,
                    "items": [{
                        "offer_id": st.session_state.order_offer_id,
                        "quantity": st.session_state.order_quantity,
                        "unit_price_minor": st.session_state.order_unit_price,
                        "total_minor": total_minor
                    }]
                }
                
                status_code, response = api_call("POST", url, payload)
                show_response(status_code, response, "Create Order")
                show_curl("Create Order", "POST", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    if "order_id" in response:
                        st.session_state.order_id = response["order_id"]
            else:
                st.error("Please provide all required fields")
    
    with col2:
        st.subheader("Order Management")
        
        if st.button("📋 List Orders"):
            url = f"{ORDERS_BASE}/orders/v2"
            params = {}
            if st.session_state.tenant_id:
                params["tenant_id"] = st.session_state.tenant_id
            
            status_code, response = api_call("GET", url, params=params)
            show_response(status_code, response, "List Orders")
        
        st.text_input("Order ID for Details", key="order_detail_id", value=st.session_state.order_id)
        
        if st.button("🔍 Get Order Details"):
            if st.session_state.order_detail_id:
                url = f"{ORDERS_BASE}/orders/v2/{st.session_state.order_detail_id}"
                status_code, response = api_call("GET", url)
                show_response(status_code, response, "Order Details")
        
        # Returns and Refunds
        st.subheader("Returns & Refunds")
        
        if st.button("↩️ Create Return"):
            if st.session_state.order_detail_id:
                url = f"{ORDERS_BASE}/orders/v2/returns"
                payload = {
                    "order_id": st.session_state.order_detail_id,
                    "reason": "Customer request",
                    "total_minor": 299
                }
                
                status_code, response = api_call("POST", url, payload)
                show_response(status_code, response, "Create Return")
                show_curl("Create Return", "POST", url, payload)

# ===== Browse & Reports =====
with tabs[6]:
    st.header("📊 Browse & Reports")
    st.markdown("Browse data and generate reports across all services")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Data Browser")
        
        service_choice = st.selectbox("Choose Service", ["Provisioning", "Orders", "Pricing"])
        
        if service_choice == "Provisioning":
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "tenants", "sites", "stores", "users", "vendors"
            ])
            base_url = PROVISIONING_BASE
            full_url = f"{base_url}/provisioning/v2/{endpoint_choice}"
        
        elif service_choice == "Orders":
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "orders", "returns", "refunds"
            ])
            base_url = ORDERS_BASE
            full_url = f"{base_url}/orders/v2"
            if endpoint_choice != "orders":
                full_url += f"/{endpoint_choice}"
        
        else:  # Pricing
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "pricebooks", "price-rules", "calculated-prices"
            ])
            base_url = PRICING_BASE
            full_url = f"{base_url}/pricing/v2/{endpoint_choice}"
        
        if st.button("🔍 Browse Data"):
            status_code, response = api_call("GET", full_url)
            show_response(status_code, response, f"Browse {endpoint_choice}")
            
            # Show data in table format if it's a list
            if isinstance(response, list) and response:
                st.subheader(f"📋 {endpoint_choice.title()} ({len(response)} items)")
                
                # Convert to DataFrame-like structure for display
                for i, item in enumerate(response):
                    with st.expander(f"Item {i+1}: {item.get('name', item.get('id', 'Unknown'))}", expanded=False):
                        st.json(item)
    
    with col2:
        st.subheader("System Health")
        
        if st.button("🏥 Check All Services"):
            health_status = check_service_health()
            
            for service_name, status in health_status.items():
                if "Healthy" in status:
                    st.success(f"{service_name}: {status}")
                elif "Status:" in status:
                    st.warning(f"{service_name}: {status}")
                else:
                    st.error(f"{service_name}: {status}")
        
        st.subheader("Quick Actions")
        
        if st.button("🧹 Clear Session State"):
            for key in list(st.session_state.keys()):
                if key not in ["tenant_id", "site_id", "store_id", "user_id"]:
                    del st.session_state[key]
            st.success("Session state cleared!")
            st.rerun()
        
        if st.button("🔄 Reset All IDs"):
            st.session_state.tenant_id = ""
            st.session_state.site_id = ""
            st.session_state.store_id = ""
            st.session_state.user_id = ""
            st.session_state.vendor_id = ""
            st.session_state.order_id = ""
            st.success("All IDs reset!")
            st.rerun()

# Footer
st.markdown("---")
st.markdown("""
**ZeroQue V2 Multi-Tenant Marketplace Platform**  
🚀 Complete architecture with provisioning, orders, and pricing services  
📚 See `README_v2.md` for detailed documentation
""")
