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
CATALOG_BASE = os.getenv("CATALOG_BASE", "http://localhost:8000")
ORDERS_BASE = os.getenv("ORDERS_BASE", "http://localhost:8203")
PRICING_BASE = os.getenv("PRICING_BASE", "http://localhost:8209")
ENTITLEMENTS_BASE = os.getenv("ENTITLEMENTS_BASE", "http://localhost:8211")

# Service status
SERVICES = {
    "Provisioning": PROVISIONING_BASE,
    "Catalog": CATALOG_BASE,
    "Orders": ORDERS_BASE,
    "Pricing": PRICING_BASE,
    "Entitlements": ENTITLEMENTS_BASE,
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
            r = requests.post(url, json=payload, params=params, timeout=20)
        elif method.upper() == "PUT":
            r = requests.put(url, json=payload, params=params, timeout=20)
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

def minor_to_gbp(minor_units: int) -> str:
    """Convert minor units to GBP display format"""
    return f"£{minor_units / 100:.2f}"

def show_response(status_code: int, response: dict, title: str = "Response"):
    """Display API response with formatting"""
    if status_code >= 200 and status_code < 300:
        st.success(f"✅ {title} - Status: {status_code}")
    else:
        st.error(f"❌ {title} - Status: {status_code}")
    
    with st.expander("Response Details", expanded=False):
        st.json(response)

def show_curl(title: str, method: str, url: str, payload: dict = None, params: dict = None):
    """Show curl command for API call"""
    with st.expander(f"🔧 {title} - cURL", expanded=False):
        # Build URL with query parameters
        full_url = url
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{url}?{query_string}"
        
        if payload:
            cmd = f"""curl -X {method.upper()} "{full_url}" \\
  -H "Content-Type: application/json" \\
  -d '{json.dumps(payload, indent=2)}'"""
        else:
            cmd = f'curl -X {method.upper()} "{full_url}"'
        st.code(cmd, language="bash")

# -------------------- Session State --------------------
defaults = {
    # Tenant Management
    "tenant_id": "",
    "tenant_id_input": "",
    "tenant_name": "Test End User Tenant",
    "tenant_type": "end_user",
    "scenario_id": "",
    
    # Site Management
    "site_id": "",
    "site_id_input": "",
    "site_tenant_id": "",
    "site_name": "Test Onsite Site",
    "site_type": "onsite",
    "site_address": "123 Main St, London, UK",
    "site_geo_lat": 51.5074,
    "site_geo_lng": -0.1278,
    
    # Store Management
    "store_id": "",
    "store_id_input": "",
    "store_site_id": "",
    "store_name": "Test Onsite Store",
    "store_type": "unmanned_onsite",
    "store_address": "456 High St, London, UK",
    "store_geo_lat": 51.5074,
    "store_geo_lng": -0.1278,
    
    # User Management
    "user_id": "",
    "user_id_input": "",
    "user_email": "",
    "user_display_name": "Admin User",
    "user_active": True,
    
    # Vendor Management
    "vendor_id": "",
    "vendor_id_input": "",
    "vendor_name": "Premium Vendors Ltd",
    "vendor_description": "Premium product supplier",
    "vendor_rating": 4.5,
    "vendor_tenant_id": "",
    
    # Product Management
    "product_master_id": "",
    "product_name": "Premium Coffee",
    "product_description": "High-quality coffee beans",
    "product_variant_id": "",
    "variant_name": "Medium Roast",
    "variant_sku": "COFFEE-MED-001",
    
    # Pricing
    "pricebook_id": "",
    "pricebook_id_input": "",
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

# Add expandable help section
with st.expander("📚 **Platform Concepts & Help**", expanded=False):
    st.markdown("""
    ### 🏢 **Tenant Types (Scenario-Specific)**
    - **`end_user`**: Large end-user sites - enforces budgets/approvals, onsite stores for employees
    - **`retailer`**: Retail businesses - guest/loyalty focus, payments/analytics, unmanned public stores
    - **`distributor`**: Distribution companies - control tower, global catalog, client installs, ERP sync
    - **`custom`**: Flexible type for special use cases
    
    ### 🎯 **Key Concepts**
    - **Scenario ID**: Business scenarios (retail_scenario, b2b_scenario, wholesale_scenario)
    - **Site Types**: onsite (end users with budgets, M:N tenant_sites), retail (retailer public guest access), distributor (distributor client installs with ERP sync)
    - **Store Types**: unmanned_onsite (budgets/approvals), unmanned_public (guest/loyalty), unmanned_distributed (global catalog)
    - **Vendor Rating**: Performance score (0-5), entered by the user
    - **Lat/Long**: Geographic coordinates for regional pricing and compliance (future proof and optional for now)
    
    ### 💰 **Pricing System**
    - **Minor Units**: Prices in pence/cents (299 = £2.99) - avoids floating-point errors, faster processing
    - **Pricebooks**: Hierarchical pricing for customer segments, regions, time periods, volume tiers
    - **Price Resolution**: Final price = pricebooks → rules → currency conversion
    - **Unit Price**: Individual item price before quantity multiplication
    
    ### 🔗 **M:N Relationships**
    - **Tenants ↔ Sites**: One tenant can have multiple sites, sites can serve multiple tenants
    - **Sites ↔ Stores**: One site can have multiple stores, stores can belong to multiple sites  
    - **Stores ↔ Vendors**: One store can have multiple vendors, vendors can serve multiple stores
    - Check relationships via **Browse & Reports** → Data Browser endpoints
    
    ### 🧹 **Session Management**
    - **Clear Session State**: Removes form data but keeps core IDs (tenant, site, store, user)
    - **Reset All IDs**: Complete fresh start - clears ALL entity IDs, forces recreation
    """)

st.markdown("---")

# Service Health Status
with st.expander("🏥 Service Health Status", expanded=False):
    health_status = check_service_health()
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.write(f"**Provisioning** (Port 8201)")
        st.write(health_status.get("Provisioning", "❌ Unknown"))
    
    with col2:
        st.write(f"**Orders** (Port 8203)")
        st.write(health_status.get("Orders", "❌ Unknown"))
    
    with col3:
        st.write(f"**Pricing** (Port 8209)")
        st.write(health_status.get("Pricing", "❌ Unknown"))
    
    with col4:
        st.write(f"**Entitlements** (Port 8211)")
        st.write(health_status.get("Entitlements", "❌ Unknown"))

# Main Tabs
tabs = st.tabs([
    "🏢 Tenant Management",
    "🎫 Entitlements & Subscriptions",
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
            st.session_state.tenant_id_input = generate_uuid()
        
        st.text_input("Tenant ID", key="tenant_id_input", help="UUID for the tenant", value=st.session_state.tenant_id)
        st.text_input("Tenant Name", key="tenant_name", help="Name of your marketplace, customer, or enterprise")
        st.selectbox("Tenant Type", ["end_user", "retailer", "distributor", "custom"], key="tenant_type", 
                    help="end_user=budgets/approvals, retailer=guest/loyalty, distributor=control tower/global catalog, custom=flexible")
        st.text_input("Scenario ID (Optional)", key="scenario_id", 
                     help="Business scenario: retail_scenario, b2b_scenario, wholesale_scenario")
        
        if st.button("💾 Create Tenant"):
            if st.session_state.tenant_name:
                # Use PUT with UUID for tenant creation
                tenant_id = st.session_state.tenant_id_input or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/tenants/{tenant_id}"
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
                    # Update the input field using st.rerun() to avoid session state conflict
                    st.rerun()
            else:
                st.error("Please provide Tenant ID and Name")
        
        # Show functionality mapping based on tenant type
        if st.session_state.tenant_type:
            st.subheader("🎯 Functionality Mapping")
            if st.session_state.tenant_type == "end_user":
                st.info("**End User Features:** Budgets & Approvals, Cost Centers, Approval Chains, Ledger Entries")
            elif st.session_state.tenant_type == "retailer":
                st.info("**Retailer Features:** Guest Access, Loyalty Programs, Usage Analytics, Public Stores")
            elif st.session_state.tenant_type == "distributor":
                st.info("**Distributor Features:** Control Tower, Global Catalog, ERP Sync, Cross-Tenant Visibility")
            elif st.session_state.tenant_type == "custom":
                st.info("**Custom Features:** Flexible configuration for special use cases")
    
    with col2:
        st.subheader("List Tenants")
        
        if st.button("📋 Fetch Tenants"):
            url = f"{PROVISIONING_BASE}/provisioning/tenants"
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

# ===== Entitlements & Subscriptions =====
with tabs[1]:
    st.header("🎫 Entitlements & Subscriptions")
    st.markdown("Manage tenant entitlements, subscriptions, and feature flags")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Subscription Plans")
        
        if st.button("📋 List Plans"):
            status_code, response = api_call("GET", f"{ENTITLEMENTS_BASE}/entitlements/v2/plans")
            if status_code == 200:
                plans = response.get("plans", [])
                st.write(f"**Found {len(plans)} plans:**")
                for plan in plans:
                    with st.expander(f"📦 {plan.get('name', 'Unknown')} ({plan.get('code', 'N/A')})"):
                        st.json(plan)
            else:
                show_response(status_code, response, "List Plans")
        
        st.subheader("Features")
        
        if st.button("🔧 List Features"):
            status_code, response = api_call("GET", f"{ENTITLEMENTS_BASE}/entitlements/v2/features")
            if status_code == 200:
                features = response.get("features", [])
                st.write(f"**Found {len(features)} features:**")
                for feature in features:
                    with st.expander(f"⚙️ {feature.get('name', 'Unknown')} ({feature.get('code', 'N/A')})"):
                        st.json(feature)
            else:
                show_response(status_code, response, "List Features")
        
        st.subheader("Create Subscription")
        
        st.text_input("Tenant ID", key="sub_tenant_id", value=st.session_state.tenant_id)
        st.selectbox("Plan Code", ["core", "enterprise", "pro"], key="sub_plan_code")
        st.selectbox("Provider", ["stripe", "trade_account"], key="sub_provider")
        st.text_input("External ID", key="sub_external_id", value=f"sub_{generate_uuid()[:8]}")
        
        if st.button("💳 Create Subscription"):
            if st.session_state.sub_tenant_id and st.session_state.sub_plan_code:
                payload = {
                    "tenant_id": st.session_state.sub_tenant_id,
                    "plan_code": st.session_state.sub_plan_code,
                    "provider": st.session_state.sub_provider,
                    "external_id": st.session_state.sub_external_id
                }
                status_code, response = api_call("POST", f"{ENTITLEMENTS_BASE}/entitlements/v2/subscriptions", payload)
                show_response(status_code, response, "Create Subscription")
            else:
                st.error("Please provide Tenant ID and Plan Code")
    
    with col2:
        st.subheader("Feature Flags")
        
        st.text_input("Tenant ID for Flags", key="flag_tenant_id", value=st.session_state.tenant_id)
        
        if st.button("🚩 Get Feature Flags"):
            if st.session_state.flag_tenant_id:
                status_code, response = api_call("GET", f"{ENTITLEMENTS_BASE}/entitlements/v2/feature-flags/{st.session_state.flag_tenant_id}")
                if status_code == 200:
                    flags = response.get("feature_flags", {})
                    st.write(f"**Found {len(flags)} feature flags:**")
                    for key, flag in flags.items():
                        with st.expander(f"🚩 {key} ({'✅' if flag.get('enabled') else '❌'})"):
                            st.json(flag)
                else:
                    show_response(status_code, response, "Get Feature Flags")
            else:
                st.error("Please provide Tenant ID")
        
        st.subheader("Create Feature Flag")
        
        st.text_input("Feature Flag Key", key="flag_key", value="new_feature")
        st.checkbox("Enabled", key="flag_enabled", value=True)
        st.text_input("Variant (optional)", key="flag_variant", value="v1")
        
        if st.button("🚩 Create Feature Flag"):
            if st.session_state.flag_tenant_id and st.session_state.flag_key:
                payload = {
                    "tenant_id": st.session_state.flag_tenant_id,
                    "key": st.session_state.flag_key,
                    "enabled": st.session_state.flag_enabled,
                    "variant": st.session_state.flag_variant if st.session_state.flag_variant else None
                }
                status_code, response = api_call("POST", f"{ENTITLEMENTS_BASE}/entitlements/v2/feature-flags", payload)
                show_response(status_code, response, "Create Feature Flag")
            else:
                st.error("Please provide Tenant ID and Feature Flag Key")
        
        st.subheader("Usage Events")
        
        st.text_input("Tenant ID for Usage", key="usage_tenant_id", value=st.session_state.tenant_id)
        st.text_input("Site ID (optional)", key="usage_site_id", value=st.session_state.site_id)
        st.text_input("Store ID (optional)", key="usage_store_id", value=st.session_state.store_id)
        st.selectbox("Meter Code", ["api_calls", "orders", "unique_shoppers", "webhook_volume", "notifications_sent", "storage_bytes", "camera_count", "uptime_minutes"], key="usage_meter_code")
        st.text_input("Subject ID (optional)", key="usage_subject_id", value="user-123")
        st.number_input("Value", min_value=1, value=1, key="usage_value")
        
        if st.button("📊 Record Usage Event"):
            if st.session_state.usage_tenant_id and st.session_state.usage_meter_code:
                payload = {
                    "tenant_id": st.session_state.usage_tenant_id,
                    "site_id": st.session_state.usage_site_id if st.session_state.usage_site_id else None,
                    "store_id": st.session_state.usage_store_id if st.session_state.usage_store_id else None,
                    "meter_code": st.session_state.usage_meter_code,
                    "subject_id": st.session_state.usage_subject_id if st.session_state.usage_subject_id else None,
                    "value": st.session_state.usage_value
                }
                status_code, response = api_call("POST", f"{ENTITLEMENTS_BASE}/entitlements/v2/usage/events", payload)
                show_response(status_code, response, "Record Usage Event")
            else:
                st.error("Please provide Tenant ID and Meter Code")
        
        st.subheader("Direct Entitlements")
        
        st.text_input("Tenant ID for Direct", key="direct_tenant_id", value=st.session_state.tenant_id)
        st.text_input("Site ID for Direct", key="direct_site_id", value=st.session_state.site_id)
        st.text_input("Feature Name", key="direct_feature", value="advanced_analytics")
        st.checkbox("Feature Enabled", key="direct_enabled", value=True)
        
        if st.button("🎯 Create Direct Entitlement"):
            if st.session_state.direct_tenant_id and st.session_state.direct_site_id and st.session_state.direct_feature:
                payload = {
                    "tenant_id": st.session_state.direct_tenant_id,
                    "site_id": st.session_state.direct_site_id,
                    "feature": st.session_state.direct_feature,
                    "enabled": st.session_state.direct_enabled
                }
                status_code, response = api_call("POST", f"{ENTITLEMENTS_BASE}/entitlements/v2/direct", payload)
                show_response(status_code, response, "Create Direct Entitlement")
            else:
                st.error("Please provide Tenant ID, Site ID, and Feature Name")

# ===== Site & Store Management =====
with tabs[2]:
    st.header("🏪 Site & Store Management")
    st.markdown("Manage sites and stores in the marketplace")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Site Management")
        
        if st.button("🎲 Generate Site ID"):
            st.session_state.site_id_input = generate_uuid()
        
        st.text_input("Site ID", key="site_id_input", value=st.session_state.site_id)
        st.text_input("Tenant ID", key="site_tenant_id", value=st.session_state.tenant_id, help="Tenant ID for this site")
        st.text_input("Site Name", key="site_name")
        st.selectbox("Site Type", ["onsite", "retail", "distributor"], key="site_type",
                    help="onsite=end users with budgets (M:N tenant_sites), retail=retailer public guest access, distributor=distributor client installs with ERP sync")
        st.text_input("Address", key="site_address", help="Full address for delivery and compliance")
        st.number_input("Latitude (optional)", key="site_geo_lat", format="%.6f", value=0.0,
                       help="Geographic coordinate for location-based services (e.g., 51.5074 for London)")
        st.number_input("Longitude (optional)", key="site_geo_lng", format="%.6f", value=0.0,
                       help="Geographic coordinate for location-based services (e.g., -0.1278 for London)")
        
        if st.button("💾 Create Site"):
            if st.session_state.site_name and st.session_state.site_tenant_id:
                # Use PUT with UUID for site creation
                site_id = st.session_state.site_id_input or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/sites/{site_id}"
                payload = {
                    "name": st.session_state.site_name,
                    "site_type": st.session_state.site_type
                }
                
                # Add optional geo information if provided (skip if 0.000)
                if (st.session_state.site_geo_lat and st.session_state.site_geo_lng and 
                    st.session_state.site_geo_lat != 0.0 and st.session_state.site_geo_lng != 0.0):
                    payload["geo"] = {
                        "lat": st.session_state.site_geo_lat,
                        "lng": st.session_state.site_geo_lng,
                        "address": st.session_state.site_address
                    }
                
                # Add tenant_id as query parameter
                params = {"tenant_id": st.session_state.site_tenant_id}
                status_code, response = api_call("PUT", url, payload, params)
                show_response(status_code, response, "Create Site")
                show_curl("Create Site", "PUT", url, payload, params)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.site_id = site_id
                    # Update the input field using st.rerun() to avoid session state conflict
                    st.rerun()
            else:
                if not st.session_state.site_name:
                    st.error("Please provide Site Name")
                if not st.session_state.site_tenant_id:
                    st.error("Please provide Tenant ID")
        
        # Show functionality mapping based on site type
        if st.session_state.site_type:
            st.subheader("🎯 Site Functionality")
            if st.session_state.site_type == "onsite":
                st.info("**Onsite Features:** M:N tenant_sites, Budget Controls, Employee Access, Cost Center Integration")
            elif st.session_state.site_type == "retail":
                st.info("**Retail Features:** Public Guest Access, Usage Analytics, No Budget Controls, Retail Focus")
            elif st.session_state.site_type == "distributor":
                st.info("**Distributor Features:** ERP Sync, Client Installs, Global Catalog Access, Cross-Tenant Operations")
        
        if st.button("📋 List Sites"):
            url = f"{PROVISIONING_BASE}/provisioning/sites"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} sites")
                
                if response:
                    for site in response:
                        with st.expander(f"🏪 {site.get('name', 'Unknown')} - {site.get('site_id', 'No ID')}", expanded=False):
                            st.json(site)
                else:
                    st.info("No sites found")
            else:
                show_response(status_code, response, "List Sites")
    
    with col2:
        st.subheader("Store Management")
        
        if st.button("🎲 Generate Store ID"):
            st.session_state.store_id_input = generate_uuid()
        
        st.text_input("Store ID", key="store_id_input", value=st.session_state.store_id)
        st.text_input("Site ID", key="store_site_id", value=st.session_state.site_id, help="Site ID for this store")
        st.text_input("Store Name", key="store_name")
        st.selectbox("Store Type", ["unmanned_onsite", "unmanned_public", "unmanned_distributed"], key="store_type",
                    help="unmanned_onsite=budgets/approvals for end users, unmanned_public=guest/loyalty for retailers, unmanned_distributed=global catalog for distributors")
        st.text_input("Store Address", key="store_address", help="Customer-facing address for this store location")
        st.number_input("Store Latitude (optional)", key="store_geo_lat", format="%.6f", value=0.0,
                       help="Precise location for delivery routing and regional analytics")
        st.number_input("Store Longitude (optional)", key="store_geo_lng", format="%.6f", value=0.0,
                       help="Precise location for delivery routing and regional analytics")
        
        if st.button("💾 Create Store"):
            if st.session_state.store_name and st.session_state.store_site_id:
                # Use PUT with UUID for store creation
                store_id = st.session_state.store_id_input or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/stores/{store_id}"
                payload = {
                    "name": st.session_state.store_name,
                    "store_type": st.session_state.store_type
                }
                
                # Add optional geo information if provided (skip if 0.000)
                if (st.session_state.store_geo_lat and st.session_state.store_geo_lng and 
                    st.session_state.store_geo_lat != 0.0 and st.session_state.store_geo_lng != 0.0):
                    payload["geo"] = {
                        "lat": st.session_state.store_geo_lat,
                        "lng": st.session_state.store_geo_lng,
                        "address": st.session_state.store_address
                    }
                
                # Add site_id as query parameter
                params = {"site_id": st.session_state.store_site_id}
                status_code, response = api_call("PUT", url, payload, params)
                show_response(status_code, response, "Create Store")
                show_curl("Create Store", "PUT", url, payload, params)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.store_id = store_id
                    # Update the input field using st.rerun() to avoid session state conflict
                    st.rerun()
            else:
                if not st.session_state.store_name:
                    st.error("Please provide Store Name")
                if not st.session_state.store_site_id:
                    st.error("Please provide Site ID")
        
        # Show functionality mapping based on store type
        if st.session_state.store_type:
            st.subheader("🎯 Store Functionality")
            if st.session_state.store_type == "unmanned_onsite":
                st.info("**Unmanned Onsite Features:** Budgets & Approvals, Employee Access, Cost Center Integration, Internal Use")
            elif st.session_state.store_type == "unmanned_public":
                st.info("**Unmanned Public Features:** Guest Access, Loyalty Programs, Public Retail, No Budget Controls")
            elif st.session_state.store_type == "unmanned_distributed":
                st.info("**Unmanned Distributed Features:** Global Catalog, Cross-Tenant Visibility, Distributor Operations")
        
        if st.button("📋 List Stores"):
            url = f"{PROVISIONING_BASE}/provisioning/stores"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} stores")
                
                if response:
                    for store in response:
                        with st.expander(f"🏬 {store.get('name', 'Unknown')} - {store.get('store_id', 'No ID')}", expanded=False):
                            st.json(store)
                else:
                    st.info("No stores found")
            else:
                show_response(status_code, response, "List Stores")

# ===== User & Vendor Management =====
with tabs[3]:
    st.header("👥 User & Vendor Management")
    st.markdown("Manage users and vendors in the marketplace")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("User Management")
        
        if st.button("🎲 Generate User ID"):
            st.session_state.user_id_input = generate_uuid()
        
        if st.button("📧 Generate Email"):
            random_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            st.session_state.user_email = f"user-{random_id}@zeroque.com"
        
        st.text_input("User ID", key="user_id_input", value=st.session_state.user_id)
        st.text_input("Email", key="user_email")
        st.text_input("Display Name", key="user_display_name")
        st.checkbox("Active", key="user_active", value=True)
        
        if st.button("👤 Create User"):
            if st.session_state.user_email and st.session_state.user_display_name:
                # Use PUT with UUID for user creation
                user_id = st.session_state.user_id_input or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/users/{user_id}"
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
                    # Update the input field using st.rerun() to avoid session state conflict
                    st.rerun()
            else:
                if not st.session_state.user_email:
                    st.error("Please provide email address")
                if not st.session_state.user_display_name:
                    st.error("Please provide display name")
        
        if st.button("📋 List Users"):
            url = f"{PROVISIONING_BASE}/provisioning/users"
            status_code, response = api_call("GET", url)
            
            # Display users in a more readable format
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                if response:
                    st.subheader("📋 Users List")
                    for user in response:
                        with st.expander(f"👤 {user.get('display_name', 'Unknown')} - {user.get('email', 'No email')}", expanded=False):
                            st.write(f"**User ID:** {user.get('user_id', 'N/A')}")
                            st.write(f"**Email:** {user.get('email', 'N/A')}")
                            st.write(f"**Display Name:** {user.get('display_name', 'N/A')}")
                            st.write(f"**Active:** {user.get('active', 'N/A')}")
                else:
                    st.info("No users found")
            else:
                show_response(status_code, response, "List Users")
    
    with col2:
        st.subheader("Vendor Management")
        
        if st.button("🎲 Generate Vendor ID"):
            st.session_state.vendor_id_input = generate_uuid()
        
        st.text_input("Vendor ID", key="vendor_id_input", value=st.session_state.vendor_id)
        st.text_input("Vendor Name", key="vendor_name", help="Business name of the vendor")
        st.text_area("Description", key="vendor_description", help="Brief description of vendor's business")
        st.number_input("Performance Score (0-5)", key="vendor_rating", min_value=0.0, max_value=5.0, step=0.1, value=0.0,
                       help="Performance score (0-5), entered by the user")
        st.text_input("Tenant ID", key="vendor_tenant_id", value=st.session_state.tenant_id, help="Tenant ID for vendor association")
        
        if st.button("🏪 Create Vendor"):
            if st.session_state.vendor_name and st.session_state.vendor_tenant_id:
                # Use PUT with UUID for vendor creation
                vendor_id = st.session_state.vendor_id_input or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/vendors/{vendor_id}"
                payload = {
                    "name": st.session_state.vendor_name,
                    "description": st.session_state.vendor_description,
                    "tenant_id": st.session_state.vendor_tenant_id
                }
                
                # Only add rating if it's greater than 0
                if st.session_state.vendor_rating > 0:
                    payload["rating"] = st.session_state.vendor_rating
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Vendor")
                show_curl("Create Vendor", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.vendor_id = vendor_id
                    # Update the input field using st.rerun() to avoid session state conflict
                    st.rerun()
            else:
                if not st.session_state.vendor_name:
                    st.error("Please provide vendor name")
                if not st.session_state.vendor_tenant_id:
                    st.error("Please provide tenant ID")
        
        if st.button("📋 List Vendors"):
            url = f"{PROVISIONING_BASE}/provisioning/vendors"
            status_code, response = api_call("GET", url)
            
            # Display vendors in a more readable format
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                if response:
                    st.subheader("📋 Vendors List")
                    for vendor in response:
                        with st.expander(f"🏪 {vendor.get('name', 'Unknown')}", expanded=False):
                            st.write(f"**Vendor ID:** {vendor.get('vendor_id', 'N/A')}")
                            st.write(f"**Name:** {vendor.get('name', 'N/A')}")
                            st.write(f"**Description:** {vendor.get('description', 'N/A')}")
                            st.write(f"**Rating:** {vendor.get('rating', 'N/A')}")
                            st.write(f"**Active:** {vendor.get('active', 'N/A')}")
                            st.write(f"**Tenant ID:** {vendor.get('tenant_id', 'N/A')}")
                else:
                    st.info("No vendors found")
            else:
                show_response(status_code, response, "List Vendors")

# ===== Product & Catalog Management =====
with tabs[4]:
    st.header("📦 Product & Catalog Management")
    st.markdown("Integrated with the ZeroQue Catalog Service V2")
    
    # Check catalog service health
    catalog_status, catalog_response = api_call("GET", f"{CATALOG_BASE}/health")
    if catalog_status == 200:
        st.success("✅ Catalog Service is running")
    else:
        st.error("❌ Catalog Service is not available")
        st.info("Please ensure the catalog service is running on http://localhost:8000")
        st.stop()
    
    # Catalog Management Tabs
    catalog_tabs = st.tabs([
        "🏢 Vendor Management",
        "📦 Product Management", 
        "🎯 Assortment Management",
        "💰 Vendor Offers",
        "📊 Service Health"
    ])
    
    # ===== Vendor Management =====
    with catalog_tabs[0]:
        st.subheader("🏢 Vendor Management")
        
    col1, col2 = st.columns(2)
    
    with col1:
            st.markdown("**Create/Update Vendor**")
            vendor_id = st.text_input("Vendor ID", value=st.session_state.get("vendor_id", ""), key="catalog_vendor_id_input")
            if not vendor_id:
                vendor_id = generate_uuid()
                st.session_state.vendor_id = vendor_id
                st.info(f"Generated Vendor ID: {vendor_id}")
            
            vendor_name = st.text_input("Vendor Name", key="catalog_vendor_name")
            vendor_description = st.text_area("Vendor Description", key="catalog_vendor_description")
            vendor_rating = st.slider("Vendor Rating", 0.0, 5.0, 4.5, 0.1, key="catalog_vendor_rating")
            
            if st.button("🏢 Create/Update Vendor"):
                payload = {
                    "tenant_id": st.session_state.get("tenant_id", ""),
                    "name": vendor_name,
                    "description": vendor_description,
                    "rating": vendor_rating,
                    "active": True
                }
                
                if not payload["tenant_id"]:
                    st.error("Please create a tenant first in the Tenant Management tab")
                else:
                    status, response = api_call("POST", f"{CATALOG_BASE}/catalog/v2/vendors/{vendor_id}", payload)
                    show_response(status, response, "Vendor Creation")
                    show_curl("Create Vendor", "POST", f"{CATALOG_BASE}/catalog/v2/vendors/{vendor_id}", payload)
    
    with col2:
            st.markdown("**List Vendors**")
            if st.button("📋 List All Vendors"):
                params = {"tenant_id": st.session_state.get("tenant_id", ""), "limit": 50}
                status, response = api_call("GET", f"{CATALOG_BASE}/catalog/v2/vendors", params=params)
                show_response(status, response, "Vendor List")
                
                if status == 200 and isinstance(response, list):
                    st.success(f"Found {len(response)} vendors")
                    for vendor in response[:5]:  # Show first 5
                        st.json(vendor)
    
    # ===== Product Management =====
    with catalog_tabs[1]:
        st.subheader("📦 Product Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Create Product Master**")
            product_id = st.text_input("Product ID", value=st.session_state.get("product_id", ""), key="catalog_product_id_input")
            if not product_id:
                product_id = generate_uuid()
                st.session_state.product_id = product_id
                st.info(f"Generated Product ID: {product_id}")
            
            product_name = st.text_input("Product Name", key="product_name")
            product_description = st.text_area("Product Description", key="product_description")
            product_brand = st.text_input("Brand", key="product_brand")
            
            st.markdown("**Category Hierarchy**")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                level1 = st.text_input("Level 1", key="category_level1", placeholder="Electronics")
            with col_b:
                level2 = st.text_input("Level 2", key="category_level2", placeholder="Computers")
            with col_c:
                level3 = st.text_input("Level 3", key="category_level3", placeholder="Laptops")
            
            # Search terms removed as requested
            
            if st.button("📦 Create Product Master"):
                category_hierarchy = {}
                if level1: category_hierarchy["level1"] = level1
                if level2: category_hierarchy["level2"] = level2
                if level3: category_hierarchy["level3"] = level3
                
                payload = {
                    "name": product_name,
                    "description": product_description,
                    "brand": product_brand,
                    "category_hierarchy": category_hierarchy if category_hierarchy else None,
                    # search_terms removed as requested
                    "active": True
                }
                
                status, response = api_call("POST", f"{CATALOG_BASE}/catalog/v2/products/{product_id}", payload)
                show_response(status, response, "Product Creation")
                show_curl("Create Product", "POST", f"{CATALOG_BASE}/catalog/v2/products/{product_id}", payload)
        
        with col2:
            st.markdown("**Create Product Variant**")
            variant_id = st.text_input("Variant ID", value=st.session_state.get("variant_id", ""), key="catalog_variant_id_input")
            if not variant_id:
                variant_id = generate_uuid()
                st.session_state.variant_id = variant_id
                st.info(f"Generated Variant ID: {variant_id}")
            
            variant_sku = st.text_input("SKU", key="variant_sku", placeholder="DELL-LAT-5520-001")
            variant_gtin = st.text_input("GTIN", key="variant_gtin", placeholder="1234567890123")
            variant_mpn = st.text_input("MPN", key="variant_mpn", placeholder="DELL-LAT-5520")
            variant_uom = st.selectbox("Unit of Measure", ["EA", "KG", "L", "M"], key="variant_uom")
            variant_weight = st.number_input("Weight (grams)", key="variant_weight", min_value=0, value=1500)
            
            if st.button("🔄 Create Product Variant"):
                if not st.session_state.get("product_id"):
                    st.error("Please create a product master first")
                else:
                    payload = {
                        "product_id": st.session_state.product_id,
                        "sku": variant_sku,
                        "gtin": variant_gtin,
                        "mpn": variant_mpn,
                        "uom": variant_uom,
                        "weight_grams": variant_weight,
                        "package_quantity": 1,
                        "active": True
                    }
                    
                    status, response = api_call("POST", f"{CATALOG_BASE}/catalog/v2/variants/{variant_id}", payload)
                    show_response(status, response, "Variant Creation")
                    show_curl("Create Variant", "POST", f"{CATALOG_BASE}/catalog/v2/variants/{variant_id}", payload)
    
    # ===== Assortment Management =====
    with catalog_tabs[2]:
        st.subheader("🎯 Assortment Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Create Store Assortment**")
            assortment_id = st.text_input("Assortment ID", value=st.session_state.get("assortment_id", ""), key="catalog_assortment_id_input")
            if not assortment_id:
                assortment_id = generate_uuid()
                st.session_state.assortment_id = assortment_id
                st.info(f"Generated Assortment ID: {assortment_id}")
            
            assortment_name = st.text_input("Assortment Name", key="assortment_name")
            assortment_description = st.text_area("Assortment Description", key="assortment_description")
            assortment_status = st.selectbox("Status", ["active", "inactive"], key="assortment_status")
            
            if st.button("🎯 Create Store Assortment"):
                if not st.session_state.get("store_id"):
                    st.error("Please create a store first in the Store Management tab")
                else:
                    payload = {
                        "store_id": st.session_state.store_id,
                        "name": assortment_name,
                        "description": assortment_description,
                        "status": assortment_status,
                        "effective_from": datetime.now().isoformat() + "Z",
                        "effective_until": None,
                        "active": True
                    }
                    
                    status, response = api_call("POST", f"{CATALOG_BASE}/catalog/v2/assortments/{assortment_id}", payload)
                    show_response(status, response, "Assortment Creation")
                    show_curl("Create Assortment", "POST", f"{CATALOG_BASE}/catalog/v2/assortments/{assortment_id}", payload)
        
        with col2:
            st.markdown("**List Store Assortments**")
            if st.button("📋 List Assortments"):
                params = {"store_id": st.session_state.get("store_id", ""), "limit": 50}
                status, response = api_call("GET", f"{CATALOG_BASE}/catalog/v2/assortments", params=params)
                show_response(status, response, "Assortment List")
    
    # ===== Vendor Offers =====
    with catalog_tabs[3]:
        st.subheader("💰 Vendor Offers")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Create Vendor Offer**")
            offer_id = st.text_input("Offer ID", value=st.session_state.get("offer_id", ""), key="catalog_offer_id_input")
            if not offer_id:
                offer_id = generate_uuid()
                st.session_state.offer_id = offer_id
                st.info(f"Generated Offer ID: {offer_id}")
            
            vendor_sku = st.text_input("Vendor SKU", key="vendor_offer_sku", placeholder="TECH-DELL-LAT-5520")
            vendor_product_name = st.text_input("Vendor Product Name", key="vendor_product_name")
            base_price_minor = st.number_input("Base Price (pence)", key="base_price_minor", min_value=0, value=89900)
            cost_price_minor = st.number_input("Cost Price (pence)", key="cost_price_minor", min_value=0, value=75000)
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"], key="offer_currency")
            min_order_qty = st.number_input("Min Order Quantity", key="min_order_qty", min_value=1, value=1)
            lead_time_days = st.number_input("Lead Time (days)", key="lead_time_days", min_value=0, value=5)
            
            if st.button("💰 Create Vendor Offer"):
                if not st.session_state.get("vendor_id") or not st.session_state.get("variant_id"):
                    st.error("Please create a vendor and variant first")
                else:
                    payload = {
                        "vendor_id": st.session_state.vendor_id,
                        "variant_id": st.session_state.variant_id,
                        "vendor_sku": vendor_sku,
                        "vendor_product_name": vendor_product_name,
                        "base_price_minor": base_price_minor,
                        "currency": currency,
                        "cost_price_minor": cost_price_minor,
                        "min_order_quantity": min_order_qty,
                        "lead_time_days": lead_time_days,
                        "tax_category": "standard",
                        "status": "active"
                    }
                    
                    status, response = api_call("POST", f"{CATALOG_BASE}/catalog/v2/vendor-offers/{offer_id}", payload)
                    show_response(status, response, "Vendor Offer Creation")
                    show_curl("Create Vendor Offer", "POST", f"{CATALOG_BASE}/catalog/v2/vendor-offers/{offer_id}", payload)
        
        with col2:
            st.markdown("**List Vendor Offers**")
            if st.button("📋 List Offers"):
                params = {"vendor_id": st.session_state.get("vendor_id", ""), "limit": 50}
                status, response = api_call("GET", f"{CATALOG_BASE}/catalog/v2/vendor-offers", params=params)
                show_response(status, response, "Vendor Offer List")
    
    # ===== Service Health =====
    with catalog_tabs[4]:
        st.subheader("📊 Catalog Service Health")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Health Check**")
            if st.button("🏥 Check Service Health"):
                status, response = api_call("GET", f"{CATALOG_BASE}/health")
                show_response(status, response, "Health Check")
        
        with col2:
            st.markdown("**Integration Test**")
            if st.button("🔧 Run Integration Test"):
                status, response = api_call("GET", f"{CATALOG_BASE}/catalog/v2/integration-test")
                show_response(status, response, "Integration Test")
        
        st.markdown("**Comprehensive Test**")
        if st.button("🧪 Run Comprehensive Test"):
            status, response = api_call("GET", f"{CATALOG_BASE}/catalog/v2/comprehensive-test")
            show_response(status, response, "Comprehensive Test")

# ===== Pricing & Pricebooks =====
with tabs[5]:
    st.header("💰 Pricing & Pricebooks")
    st.markdown("Advanced pricing engine with pricebooks and rules")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Pricebook Management")
        
        if st.button("🎲 Generate Pricebook ID"):
            st.session_state.pricebook_id_input = generate_uuid()
        
        st.text_input("Pricebook ID", key="pricebook_id_input", value=st.session_state.pricebook_id)
        st.text_input("Pricebook Name", key="pricebook_name")
        st.selectbox("Currency", ["GBP", "USD", "EUR"], key="currency")
        
        if st.button("📋 Create Pricebook"):
            if st.session_state.pricebook_name:
                # Use PUT with UUID for pricebook creation
                pricebook_id = st.session_state.pricebook_id_input or generate_uuid()
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
                    # Update the input field using st.rerun() to avoid session state conflict
                    st.rerun()
        
        if st.button("📋 List Pricebooks"):
            url = f"{PRICING_BASE}/pricing/v2/pricebooks"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} pricebooks")
                
                if response:
                    for pricebook in response:
                        with st.expander(f"📋 {pricebook.get('name', 'Unknown')} - {pricebook.get('pricebook_id', 'No ID')}", expanded=False):
                            st.json(pricebook)
                else:
                    st.info("No pricebooks found")
            else:
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
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} price rules")
                
                if response:
                    for rule in response:
                        with st.expander(f"📊 Price Rule - {rule.get('rule_id', 'No ID')}", expanded=False):
                            st.json(rule)
                else:
                    st.info("No price rules found")
            else:
                show_response(status_code, response, "List Price Rules")

# ===== Order Management =====
with tabs[6]:
    st.header("🛒 Order Management")
    st.markdown("Order processing with saga orchestration and vendor splits")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Create Order")
        
        st.text_input("Tenant ID for Order", value=st.session_state.tenant_id)
        st.text_input("Store ID for Order", value=st.session_state.store_id)
        st.text_input("Customer ID", key="customer_id", value=st.session_state.user_id)
        st.selectbox("Payment Method", ["trade", "card", "cash"], key="payment_method")
        st.selectbox("Order Currency", ["GBP", "USD", "EUR"], index=0, key="order_currency")
        
        # Order Items
        st.subheader("Order Items")
        st.text_input("Offer ID for Order", key="order_offer_id", value="550e8400-e29b-41d4-a716-446655440001")
        st.number_input("Quantity", min_value=1, value=2, key="order_quantity")
        st.number_input("Unit Price (minor)", min_value=1, value=1299, key="order_unit_price",
                       help="Price per item in minor units (1299 = £12.99). Individual item price before quantity multiplication.")
        
        if st.button("🛒 Create Order"):
            if (st.session_state.tenant_id and st.session_state.store_id and 
                st.session_state.customer_id and st.session_state.order_offer_id):
                
                total_minor = st.session_state.order_unit_price * st.session_state.order_quantity
                
                url = f"{ORDERS_BASE}/orders/v2"
                payload = {
                    "tenant_id": st.session_state.tenant_id,
                    "store_id": st.session_state.store_id,
                    "customer_id": st.session_state.customer_id,
                    "currency": st.session_state.order_currency,
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
                        total_gbp = minor_to_gbp(total_minor)
                        st.success(f"✅ Order created successfully! Order ID: {response['order_id']}")
                        st.info(f"💰 Total: {total_gbp} ({total_minor} minor units)")
                        st.rerun()
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
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} orders")
                
                if response:
                    for order in response:
                        with st.expander(f"🛒 Order - {order.get('order_id', 'No ID')}", expanded=False):
                            st.json(order)
                else:
                    st.info("No orders found")
            else:
                show_response(status_code, response, "List Orders")
        
        st.text_input("Order ID for Details", key="order_detail_id", value=st.session_state.order_id)
        
        if st.button("🔍 Get Order Details"):
            if st.session_state.order_detail_id:
                url = f"{ORDERS_BASE}/orders/v2/{st.session_state.order_detail_id}"
                status_code, response = api_call("GET", url)
                show_response(status_code, response, "Order Details")
                
                # Show order details in GBP format
                if status_code >= 200 and status_code < 300 and isinstance(response, dict):
                    if "total_minor" in response:
                        total_gbp = minor_to_gbp(response["total_minor"])
                        st.info(f"💰 Order Total: {total_gbp} ({response['total_minor']} minor units)")
                    
                    if "items" in response and isinstance(response["items"], list):
                        st.subheader("📋 Order Items")
                        for item in response["items"]:
                            if "unit_price_minor" in item and "quantity" in item:
                                unit_gbp = minor_to_gbp(item["unit_price_minor"])
                                total_item_gbp = minor_to_gbp(item["unit_price_minor"] * item["quantity"])
                                st.write(f"• {item.get('offer_id', 'Unknown')}: {item['quantity']} × {unit_gbp} = {total_item_gbp}")
        
        # Generate CSV and Show Receipt buttons
        if st.button("📄 Generate CSV"):
            if st.session_state.order_detail_id:
                url = f"{ORDERS_BASE}/orders/v2/{st.session_state.order_detail_id}"
                status_code, response = api_call("GET", url)
                if status_code >= 200 and status_code < 300 and isinstance(response, dict):
                    # Create CSV content
                    csv_content = f"Order ID,Total (GBP),Total (Minor Units),Currency,Status\n"
                    if "total_minor" in response:
                        total_gbp = minor_to_gbp(response["total_minor"])
                        csv_content += f"{response.get('order_id', '')},{total_gbp},{response['total_minor']},{response.get('currency', 'GBP')},{response.get('status', '')}\n"
                    
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv_content,
                        file_name=f"order_{st.session_state.order_detail_id}.csv",
                        mime="text/csv"
                    )
        
        if st.button("🧾 Show Receipt"):
            if st.session_state.order_detail_id:
                url = f"{ORDERS_BASE}/orders/v2/{st.session_state.order_detail_id}"
                status_code, response = api_call("GET", url)
                if status_code >= 200 and status_code < 300 and isinstance(response, dict):
                    st.subheader("🧾 Order Receipt")
                    st.write(f"**Order ID:** {response.get('order_id', 'N/A')}")
                    st.write(f"**Status:** {response.get('status', 'N/A')}")
                    st.write(f"**Currency:** {response.get('currency', 'GBP')}")
                    
                    if "total_minor" in response:
                        total_gbp = minor_to_gbp(response["total_minor"])
                        st.write(f"**Total:** {total_gbp}")
                    
                    if "items" in response and isinstance(response["items"], list):
                        st.write("**Items:**")
                        for item in response["items"]:
                            if "unit_price_minor" in item and "quantity" in item:
                                unit_gbp = minor_to_gbp(item["unit_price_minor"])
                                total_item_gbp = minor_to_gbp(item["unit_price_minor"] * item["quantity"])
                                st.write(f"• {item.get('offer_id', 'Unknown')}: {item['quantity']} × {unit_gbp} = {total_item_gbp}")
        

# ===== Browse & Reports =====
with tabs[7]:
    st.header("📊 Browse & Reports")
    st.markdown("Browse data and generate reports across all services")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Data Browser")
        
        service_choice = st.selectbox("Choose Service", ["Provisioning", "Orders", "Pricing", "Entitlements"])
        
        if service_choice == "Provisioning":
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "tenants", "sites", "stores", "users", "vendors"
            ])
            base_url = PROVISIONING_BASE
            full_url = f"{base_url}/provisioning/{endpoint_choice}"
        
        elif service_choice == "Orders":
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "orders", "returns", "refunds"
            ])
            base_url = ORDERS_BASE
            full_url = f"{base_url}/orders/v2"
            if endpoint_choice != "orders":
                full_url += f"/{endpoint_choice}"
        
        elif service_choice == "Pricing":
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "pricebooks", "price-rules", "calculated-prices"
            ])
            base_url = PRICING_BASE
            full_url = f"{base_url}/pricing/v2/{endpoint_choice}"
        
        else:  # Entitlements
            endpoint_choice = st.selectbox("Choose Endpoint", [
                "plans", "features", "subscriptions", "feature-flags", "usage-events", "direct-entitlements"
            ])
            base_url = ENTITLEMENTS_BASE
            if endpoint_choice == "plans":
                full_url = f"{base_url}/entitlements/v2/plans"
            elif endpoint_choice == "features":
                full_url = f"{base_url}/entitlements/v2/features"
            elif endpoint_choice == "subscriptions":
                full_url = f"{base_url}/entitlements/v2/subscriptions"
            elif endpoint_choice == "feature-flags":
                full_url = f"{base_url}/entitlements/v2/feature-flags"
            elif endpoint_choice == "usage-events":
                full_url = f"{base_url}/entitlements/v2/usage/events"
            elif endpoint_choice == "direct-entitlements":
                full_url = f"{base_url}/entitlements/v2/direct"
        
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
        
        st.markdown("""
        **Session Management:**
        - **Clear Session State**: Removes form data but keeps core IDs (tenant, site, store, user)
        - **Reset All IDs**: Clears all generated IDs, forcing you to create new entities
        """)
        
        if st.button("🧹 Clear Session State"):
            # Keep core infrastructure IDs but clear form data
            core_ids = ["tenant_id", "site_id", "store_id", "user_id"]
            for key in list(st.session_state.keys()):
                if key not in core_ids:
                    del st.session_state[key]
            st.success("✅ Session state cleared! Core IDs preserved.")
            st.info("Form data cleared but tenant, site, store, and user IDs kept for continuity.")
            st.rerun()
        
        if st.button("🔄 Reset All IDs"):
            # Clear ALL IDs - fresh start
            id_keys = ["tenant_id", "site_id", "store_id", "user_id", "vendor_id", "order_id", "pricebook_id", "offer_id"]
            for key in id_keys:
                if key in st.session_state:
                    st.session_state[key] = ""
            st.success("🔄 All IDs reset! You can now create fresh entities.")
            st.warning("All entity IDs cleared. You'll need to recreate tenants, sites, stores, etc.")
            st.rerun()

# ===== Database Schema Documentation =====
st.markdown("---")
st.header("📚 Database Schema & Table Relationships")

with st.expander("🏢 Tenant Management Tables", expanded=False):
    st.markdown("""
    **Core Tables:**
    - **`tenants_new`**: Master tenant records with business scenarios
    - **`tenant_links_new`**: Links between tenants for distributor relationships
    
    **Purpose**: Foundation of multi-tenancy - every entity belongs to a tenant
    **Relationships**: 
    - Tenants → Sites (1:N via `tenant_sites`)
    - Tenants → Stores (M:N via `tenant_sites` → `site_stores`)
    - Tenants → Users (1:N via `users_new.tenant_id`)
    """)

with st.expander("🎫 Entitlements & Subscriptions Tables", expanded=False):
    st.markdown("""
    **Subscription Management:**
    - **`subscriptions`**: Tenant-level subscription records (Stripe/Trade Account)
    - **`plans`**: Available subscription plans (Core, Enterprise, Pro)
    - **`features`**: Available features (API Access, Analytics, etc.)
    - **`plan_features`**: Plan-to-feature mappings with limits
    
    **Usage Tracking:**
    - **`usage_events`**: Real-time usage events (API calls, orders, etc.)
    - **`usage_meters`**: Meter definitions (api_calls, orders, unique_shoppers, etc.)
    - **`usage_aggregates_daily`**: Daily aggregated usage for billing
    
    **Feature Control:**
    - **`feature_flags`**: Tenant-level feature toggles with variants
    - **`entitlements`**: Direct site-level feature permissions
    
    **Purpose**: Tenant-level subscription management, usage tracking, and feature control
    **Relationships**:
    - Tenants → Subscriptions (1:1 via `subscriptions.tenant_id`)
    - Plans → Features (M:N via `plan_features`)
    - Tenants → Usage Events (1:N via `usage_events.tenant_id`)
    - Tenants → Feature Flags (1:N via `feature_flags.tenant_id`)
    """)

with st.expander("🏪 Site & Store Management Tables", expanded=False):
    st.markdown("""
    **Core Tables:**
    - **`sites_new`**: Physical locations (onsite, retail, distributor)
    - **`stores_new`**: Store locations within sites
    - **`tenant_sites`**: Tenant-to-site relationships (M:N)
    - **`site_stores`**: Site-to-store relationships (1:N)
    
    **Purpose**: Physical infrastructure management for multi-tenant marketplace
    **Relationships**:
    - Tenants ↔ Sites (M:N via `tenant_sites`)
    - Sites → Stores (1:N via `site_stores`)
    - Stores → Orders (1:N via `orders_new.store_id`)
    """)

with st.expander("👥 User & Vendor Management Tables", expanded=False):
    st.markdown("""
    **User Management:**
    - **`users_new`**: User accounts with roles and permissions
    - **`roles_new`**: Role definitions (admin, manager, user, etc.)
    - **`permissions_new`**: Permission definitions (read, write, delete, etc.)
    - **`role_permissions_new`**: Role-to-permission mappings
    - **`role_assignments`**: User-to-role assignments
    
    **Vendor Management:**
    - **`vendors`**: Vendor master data
    - **`vendor_onboarding`**: Vendor onboarding status
    - **`store_vendors`**: Store-to-vendor relationships
    - **`tenant_store_admins`**: Tenant store administration
    
    **Purpose**: Identity management, access control, and vendor relationships
    **Relationships**:
    - Users → Roles (M:N via `role_assignments`)
    - Roles → Permissions (M:N via `role_permissions_new`)
    - Stores → Vendors (M:N via `store_vendors`)
    """)

with st.expander("💰 Pricing & Pricebooks Tables", expanded=False):
    st.markdown("""
    **Core Tables:**
    - **`pricebooks`**: Pricebook definitions with currency
    - **`pricebook_entries`**: Product prices within pricebooks
    - **`pricebook_assignments`**: Pricebook-to-store assignments
    - **`price_rules_new`**: Advanced pricing rules
    - **`price_rule_conditions`**: Rule conditions and logic
    - **`calculated_prices`**: Cached calculated prices
    
    **Purpose**: Sophisticated pricing engine with hierarchical price resolution
    **Relationships**:
    - Pricebooks → Pricebook Entries (1:N)
    - Stores → Pricebooks (M:N via `pricebook_assignments`)
    - Price Rules → Conditions (1:N via `price_rule_conditions`)
    """)

with st.expander("🛒 Order Management Tables", expanded=False):
    st.markdown("""
    **Core Tables:**
    - **`orders_new`**: Order master records with status tracking
    - **`order_items_new`**: Order line items with pricing
    - **`sub_orders`**: Sub-orders for vendor splits
    - **`returns`**: Return requests and processing
    - **`refunds`**: Refund processing records
    
    **Purpose**: Order lifecycle management with saga orchestration
    **Relationships**:
    - Orders → Order Items (1:N via `order_items_new.order_id`)
    - Orders → Sub Orders (1:N via `sub_orders.order_id`)
    - Orders → Returns (1:N via `returns.order_id`)
    - Orders → Refunds (1:N via `refunds.order_id`)
    """)

with st.expander("🔗 Key Relationships & Data Flow", expanded=False):
    st.markdown("""
    **Data Flow:**
    1. **Tenant Creation** → **Subscription Setup** → **Site/Store Creation** → **User Management**
    2. **Product Catalog** → **Pricing Rules** → **Order Processing** → **Usage Tracking**
    3. **Feature Flags** → **Entitlement Checks** → **Access Control** → **Billing**
    
    **Critical Relationships:**
    - **Tenant** is the root entity - everything belongs to a tenant
    - **Sites** provide physical infrastructure for tenants
    - **Stores** are the point of sale within sites
    - **Users** operate within tenant context with role-based access
    - **Subscriptions** determine tenant capabilities and billing
    - **Usage Events** track consumption for billing and limits
    - **Feature Flags** enable/disable features per tenant
    - **Direct Entitlements** provide granular site-level permissions
    
    **Multi-Tenancy Model:**
    - **Tenant-Level**: Subscriptions, Feature Flags, Usage Tracking
    - **Site-Level**: Direct Entitlements, Store Management
    - **Store-Level**: Pricing, Orders, Inventory
    - **User-Level**: Access Control, Role Management
    """)

with st.expander("🎫 Entitlements System Deep Dive", expanded=True):
    st.markdown("""
    ## 🎫 Entitlements System Explained
    
    ### 📋 **Subscription Plans & Features**
    - **Plans** (Core, Enterprise, Pro): Define what features a tenant gets
    - **Features** (API Access, Analytics, etc.): Individual capabilities
    - **Plan Features**: Links plans to features with usage limits
    
    ### 💳 **Creating Subscriptions**
    - **Tenant ID**: Which tenant gets the subscription
    - **Plan Code**: Which plan (core/enterprise/pro)
    - **Provider**: Payment method (stripe/trade_account)
    - **External ID**: Reference ID from payment provider (e.g., Stripe subscription ID)
    
    ### 🚩 **Feature Flags**
    - **Tenant ID**: Which tenant the flag applies to
    - **Key**: Feature name (e.g., "new_checkout_flow")
    - **Enabled**: On/off toggle
    - **Variant**: A/B testing variant (e.g., "v1", "v2")
    
    ### 📊 **Usage Events**
    - **Tenant ID**: Which tenant used the feature
    - **Site/Store ID**: Where the usage occurred (optional)
    - **Meter Code**: What was used (api_calls, orders, etc.)
    - **Subject ID**: Who used it (user ID, optional)
    - **Value**: How much was used (count, bytes, etc.)
    
    ### 🎯 **Direct Entitlements**
    - **Tenant ID**: Which tenant
    - **Site ID**: Which site gets the permission
    - **Feature**: What feature is enabled/disabled
    - **Enabled**: Permission status
    
    ### 🔄 **How It All Works Together**
    1. **Tenant subscribes** to a plan → Gets access to plan features
    2. **Feature flags** enable/disable features per tenant
    3. **Usage events** track consumption for billing
    4. **Direct entitlements** provide granular site-level control
    5. **System checks** entitlements before allowing actions
    """)

# Footer removed as requested
