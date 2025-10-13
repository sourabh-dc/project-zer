"""
ZeroQue Provisioning Service - Streamlit Admin Interface
Comprehensive interface for managing tenants, sites, stores, users, roles, vendors, and cost centres
"""

import os
import json
import random
import string
import uuid
import requests
import streamlit as st
from datetime import datetime
from typing import Dict, List, Any

# -------------------- Config --------------------
PROVISIONING_BASE = os.getenv("PROVISIONING_BASE", "http://localhost:8000")
DEMO_API_KEY = "zq_demo_key_for_testing"

# -------------------- Session State Initialization --------------------
def init_session_state():
    """Initialize session state variables"""
    if 'tenant_id' not in st.session_state:
        st.session_state.tenant_id = ""
    if 'site_id' not in st.session_state:
        st.session_state.site_id = ""
    if 'store_id' not in st.session_state:
        st.session_state.store_id = ""
    if 'user_id' not in st.session_state:
        st.session_state.user_id = ""
    if 'vendor_id' not in st.session_state:
        st.session_state.vendor_id = ""

# -------------------- Helpers --------------------
def generate_uuid() -> str:
    """Generate a UUID for entity creation"""
    return str(uuid.uuid4())

def rid(prefix: str) -> str:
    """Generate a random ID with prefix"""
    return f"{prefix}-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

def api_call(method: str, url: str, payload: dict = None, params: dict = None):
    """Make API call with error handling"""
    try:
        # In demo mode, don't send authentication headers
        headers = {"Content-Type": "application/json"}
        
        if method.upper() == "GET":
            r = requests.get(url, params=params, headers=headers, timeout=20)
        elif method.upper() == "POST":
            r = requests.post(url, json=payload, params=params, headers=headers, timeout=20)
        elif method.upper() == "PUT":
            r = requests.put(url, json=payload, params=params, headers=headers, timeout=20)
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
            cmd = f"""curl -X {method.upper()} "{full_url}" \\
  -H "Content-Type: application/json" """
        st.code(cmd, language="bash")

# -------------------- Session State --------------------
defaults = {
    # Tenant Management
    "tenant_id": "",
    "tenant_id_input": "",
    "tenant_name": "Demo Tenant",
    "tenant_type": "customer",
    
    # Site Management
    "site_id": "",
    "site_id_input": "",
    "site_tenant_id": "",
    "site_name": "Demo Site",
    "site_type": "office",
    "site_geo_lat": 51.5074,
    "site_geo_lng": -0.1278,
    
    # Store Management
    "store_id": "",
    "store_id_input": "",
    "store_site_id": "",
    "store_name": "Demo Store",
    "store_type": "retail",
    "store_geo_lat": 51.5074,
    "store_geo_lng": -0.1278,
    
    # User Management
    "user_id": "",
    "user_id_input": "",
    "user_email": "",
    "user_display_name": "Demo User",
    "user_tenant_id": "",
    "generate_api_key": True,
    
    # Role Management
    "role_id": "",
    "role_id_input": "",
    "role_code": "demo_role",
    "role_name": "Demo Role",
    "role_description": "A demo role for testing",
    
    # Vendor Management
    "vendor_id": "",
    "vendor_id_input": "",
    "vendor_name": "Demo Vendor",
    "vendor_contact_email": "vendor@demo.com",
    "vendor_description": "A demo vendor for testing",
    "vendor_tenant_id": "",
    
    # Cost Centre Management
    "cost_centre_tenant_id": "",
    "cost_centre_name": "Demo Cost Centre",
    "cost_centre_budget_minor": 100000,  # £1000
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -------------------- Health Check --------------------
def check_service_health():
    """Check health of provisioning service"""
    try:
        response = requests.get(f"{PROVISIONING_BASE}/health", timeout=5)
        if response.status_code == 200:
            return "✅ Healthy", response.json()
        else:
            return f"⚠️ Status: {response.status_code}", None
    except Exception as e:
        return f"❌ Error: {str(e)[:50]}...", None

def fetch_tenants():
    """Fetch list of existing tenants"""
    try:
        status_code, response = api_call("GET", f"{PROVISIONING_BASE}/provisioning/tenants")
        if status_code == 200:
            return response
        else:
            return []
    except Exception as e:
        return []

# -------------------- UI --------------------
st.set_page_config(page_title="ZeroQue Provisioning Service", layout="wide")

# Initialize session state
init_session_state()

# Header
st.title("🏢 ZeroQue Provisioning Service Admin")
st.markdown("""
**Provisioning Service Features:**
- Complete saga pattern implementation for all entities
- Outbox pattern for reliable event publishing
- Row-level security (RLS) for tenant isolation
- Authentication with API keys and JWT
- Subscription limits with circuit breaker
- Comprehensive audit logging
- Celery workers for background processing

**💡 Recommended Workflow:**
1. **Create Tenant** → 2. **Create Site** → 3. **Create Store** → 4. **Create User**
""")

# Service Health Status
with st.expander("🏥 Service Health Status", expanded=False):
    health_status, health_data = check_service_health()
    st.write(f"**Provisioning Service** (Port 8000)")
    st.write(health_status)
    if health_data:
        st.json(health_data)

st.markdown("---")

# Main Tabs
tabs = st.tabs([
    "🏢 Tenant Management",
    "🏪 Site Management", 
    "🏬 Store Management",
    "👥 User Management",
    "🎭 Role Management",
    "🏪 Vendor Management",
    "💰 Cost Centre Management",
    "📊 Browse & Reports"
])

# ===== Tenant Management =====
with tabs[0]:
    st.header("🏢 Tenant Management")
    st.markdown("Create and manage tenants in the multi-tenant system")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create Tenant")
        
        if st.button("🎲 Generate Tenant ID"):
            st.session_state.tenant_id_input = generate_uuid()
        
        st.text_input("Tenant ID", key="tenant_id_input", help="UUID for the tenant", value=st.session_state.tenant_id)
        st.text_input("Tenant Name", key="tenant_name", help="Name of the tenant organization")
        st.selectbox("Tenant Type", ["customer", "partner", "vendor"], key="tenant_type", 
                    help="Type of tenant organization")
        
        if st.button("💾 Create Tenant"):
            tenant_name = st.session_state.get('tenant_name', '').strip()
            tenant_type = st.session_state.get('tenant_type', 'customer')
            
            if not tenant_name:
                st.error("❌ Please provide a valid Tenant Name")
                st.info("💡 Tenant name cannot be empty")
            else:
                tenant_id = st.session_state.get('tenant_id_input', '') or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/tenants"
                payload = {
                    "name": tenant_name,
                    "tenant_type": tenant_type
                }
                
                status_code, response = api_call("POST", url, payload)
                show_response(status_code, response, "Create Tenant")
                show_curl("Create Tenant", "POST", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    # Extract tenant_id from response
                    created_tenant_id = response.get('tenant_id', tenant_id)
                    st.session_state.tenant_id = created_tenant_id
                    st.session_state.site_tenant_id = created_tenant_id
                    st.session_state.user_tenant_id = created_tenant_id
                    st.session_state.vendor_tenant_id = created_tenant_id
                    st.session_state.cost_centre_tenant_id = created_tenant_id
                    st.success(f"✅ Tenant '{tenant_name}' created successfully!")
                    st.info(f"🆔 Tenant ID: {created_tenant_id}")
                    st.rerun()
                elif status_code == 400 and "Name exists" in str(response):
                    st.error("❌ Tenant name already exists. Please choose a different name.")
                else:
                    st.error(f"❌ Failed to create tenant. Status: {status_code}")
    
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

# ===== Site Management =====
with tabs[1]:
    st.header("🏪 Site Management")
    st.markdown("Create and manage sites within tenants")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create Site")
        
        if st.button("🎲 Generate Site ID"):
            st.session_state.site_id_input = generate_uuid()
        
        st.text_input("Site ID", key="site_id_input", value=st.session_state.site_id)
        
        # Tenant selection
        tenants = fetch_tenants()
        if tenants:
            tenant_options = {f"{t['name']} ({t['tenant_id']})": t['tenant_id'] for t in tenants}
            selected_tenant = st.selectbox(
                "Select Tenant", 
                options=list(tenant_options.keys()),
                index=0 if not st.session_state.tenant_id else None,
                help="Choose an existing tenant for this site"
            )
            if selected_tenant:
                selected_tenant_id = tenant_options[selected_tenant]
                st.session_state.site_tenant_id = selected_tenant_id
                st.session_state.tenant_id = selected_tenant_id
        else:
            st.text_input("Tenant ID", key="site_tenant_id", value=st.session_state.tenant_id, help="Tenant ID for this site")
            st.warning("⚠️ No tenants found. Please create a tenant first.")
        
        st.text_input("Site Name", key="site_name")
        st.selectbox("Site Type", ["office", "warehouse", "retail", "factory"], key="site_type",
                    help="Type of site location")
        
        st.subheader("Location (Optional)")
        st.number_input("Latitude", key="site_geo_lat", format="%.6f", value=0.0,
                       help="Geographic coordinate (e.g., 51.5074 for London)")
        st.number_input("Longitude", key="site_geo_lng", format="%.6f", value=0.0,
                       help="Geographic coordinate (e.g., -0.1278 for London)")
        
        if st.button("💾 Create Site"):
            site_name = st.session_state.get('site_name', '').strip()
            tenant_id = st.session_state.get('site_tenant_id', '') or st.session_state.get('tenant_id', '')
            
            if not site_name:
                st.error("❌ Please provide a valid Site Name")
                st.info("💡 Site name cannot be empty")
            elif not tenant_id:
                st.error("❌ Please select a tenant first")
                st.info("💡 Go to the 'Tenant Management' tab to create a tenant first")
            else:
                site_id = st.session_state.get('site_id_input', '') or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/sites/{site_id}"
                payload = {
                    "name": site_name,
                    "site_type": st.session_state.get('site_type', 'office')
                }
                
                # Add optional geo information if provided
                geo_lat = st.session_state.get('site_geo_lat', 0.0)
                geo_lng = st.session_state.get('site_geo_lng', 0.0)
                if geo_lat != 0.0 and geo_lng != 0.0:
                    payload["geo"] = {
                        "lat": geo_lat,
                        "lng": geo_lng
                    }
                
                params = {"tenant_id": tenant_id}
                status_code, response = api_call("PUT", url, payload, params)
                show_response(status_code, response, "Create Site")
                show_curl("Create Site", "PUT", url, payload, params)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.site_id = site_id
                    st.session_state.store_site_id = site_id
                    st.success(f"✅ Site '{site_name}' created successfully!")
                    st.info(f"🆔 Site ID: {site_id}")
                    st.rerun()
                elif status_code == 400 and "Tenant not found" in str(response):
                    st.error("❌ Invalid tenant ID. Please select a valid tenant.")
                elif status_code == 400 and "Limit reached" in str(response):
                    st.error("❌ Site limit reached for this tenant.")
                else:
                    st.error(f"❌ Failed to create site. Status: {status_code}")
    
    with col2:
        st.subheader("List Sites")
        
        if st.button("📋 Fetch Sites"):
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

# ===== Store Management =====
with tabs[2]:
    st.header("🏬 Store Management")
    st.markdown("Create and manage stores within sites")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create Store")
        
        if st.button("🎲 Generate Store ID"):
            st.session_state.store_id_input = generate_uuid()
        
        st.text_input("Store ID", key="store_id_input", value=st.session_state.store_id)
        st.text_input("Site ID", key="store_site_id", value=st.session_state.site_id, help="Site ID for this store")
        st.text_input("Store Name", key="store_name")
        st.selectbox("Store Type", ["retail", "warehouse", "popup", "online"], key="store_type",
                    help="Type of store")
        
        st.subheader("Location (Optional)")
        st.number_input("Store Latitude", key="store_geo_lat", format="%.6f", value=0.0,
                       help="Precise location for this store")
        st.number_input("Store Longitude", key="store_geo_lng", format="%.6f", value=0.0,
                       help="Precise location for this store")
        
        if st.button("💾 Create Store"):
            if st.session_state.store_name:
                # Auto-generate site ID if not provided
                site_id = st.session_state.store_site_id or st.session_state.site_id
                if not site_id:
                    st.error("❌ Please create a site first or provide a valid Site ID")
                    st.info("💡 Go to the 'Site Management' tab to create a site first")
                else:
                    store_id = st.session_state.store_id_input or generate_uuid()
                    url = f"{PROVISIONING_BASE}/provisioning/stores/{store_id}"
                    payload = {
                        "name": st.session_state.store_name,
                        "store_type": st.session_state.store_type
                    }
                    
                    # Add optional geo information if provided
                    if (st.session_state.store_geo_lat and st.session_state.store_geo_lng and 
                        st.session_state.store_geo_lat != 0.0 and st.session_state.store_geo_lng != 0.0):
                        payload["geo"] = {
                            "lat": st.session_state.store_geo_lat,
                            "lng": st.session_state.store_geo_lng
                        }
                    
                    params = {"site_id": site_id}
                    status_code, response = api_call("PUT", url, payload, params)
                    show_response(status_code, response, "Create Store")
                    show_curl("Create Store", "PUT", url, payload, params)
                    
                    if status_code >= 200 and status_code < 300:
                        st.session_state.store_id = store_id
                        st.rerun()
            else:
                st.error("Please provide Store Name")
    
    with col2:
        st.subheader("List Stores")
        
        if st.button("📋 Fetch Stores"):
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

# ===== User Management =====
with tabs[3]:
    st.header("👥 User Management")
    st.markdown("Create and manage users within tenants")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create User")
        
        if st.button("🎲 Generate User ID"):
            st.session_state.user_id_input = generate_uuid()
        
        if st.button("📧 Generate Email"):
            random_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            st.session_state.user_email = f"user-{random_id}@demo.com"
        
        st.text_input("User ID", key="user_id_input", value=st.session_state.user_id)
        st.text_input("Email", key="user_email")
        st.text_input("Display Name", key="user_display_name")
        st.text_input("Tenant ID", key="user_tenant_id", value=st.session_state.tenant_id, help="Tenant ID for this user")
        st.checkbox("Generate API Key", key="generate_api_key", value=True, help="Generate API key for this user")
        
        if st.button("👤 Create User"):
            if st.session_state.user_email and st.session_state.user_display_name:
                # Auto-generate tenant ID if not provided
                tenant_id = st.session_state.user_tenant_id or st.session_state.tenant_id
                if not tenant_id:
                    st.error("❌ Please create a tenant first or provide a valid Tenant ID")
                    st.info("💡 Go to the 'Tenant Management' tab to create a tenant first")
                else:
                    user_id = st.session_state.user_id_input or generate_uuid()
                    url = f"{PROVISIONING_BASE}/provisioning/users/{user_id}"
                    payload = {
                        "email": st.session_state.user_email,
                        "display_name": st.session_state.user_display_name,
                        "tenant_id": tenant_id,
                        "generate_api_key": st.session_state.generate_api_key
                    }
                    
                    status_code, response = api_call("PUT", url, payload)
                    show_response(status_code, response, "Create User")
                    show_curl("Create User", "PUT", url, payload)
                    
                    if status_code >= 200 and status_code < 300:
                        st.session_state.user_id = user_id
                        st.rerun()
            else:
                if not st.session_state.user_email:
                    st.error("Please provide email address")
                if not st.session_state.user_display_name:
                    st.error("Please provide display name")
    
    with col2:
        st.subheader("List Users")
        
        if st.button("📋 Fetch Users"):
            url = f"{PROVISIONING_BASE}/provisioning/users"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} users")
                
                if response:
                    for user in response:
                        with st.expander(f"👤 {user.get('display_name', 'Unknown')} - {user.get('email', 'No email')}", expanded=False):
                            st.json(user)
                else:
                    st.info("No users found")
            else:
                show_response(status_code, response, "List Users")

# ===== Role Management =====
with tabs[4]:
    st.header("🎭 Role Management")
    st.markdown("Create and manage roles for access control")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create Role")
        
        if st.button("🎲 Generate Role ID"):
            st.session_state.role_id_input = generate_uuid()
        
        st.text_input("Role ID", key="role_id_input", value=st.session_state.role_id)
        st.text_input("Role Code", key="role_code", help="Unique code for the role")
        st.text_input("Role Name", key="role_name")
        st.text_area("Description", key="role_description")
        
        if st.button("🎭 Create Role"):
            if st.session_state.role_code and st.session_state.role_name:
                role_id = st.session_state.role_id_input or generate_uuid()
                url = f"{PROVISIONING_BASE}/provisioning/roles/{role_id}"
                payload = {
                    "code": st.session_state.role_code,
                    "name": st.session_state.role_name,
                    "description": st.session_state.role_description
                }
                
                status_code, response = api_call("PUT", url, payload)
                show_response(status_code, response, "Create Role")
                show_curl("Create Role", "PUT", url, payload)
                
                if status_code >= 200 and status_code < 300:
                    st.session_state.role_id = role_id
                    st.rerun()
            else:
                if not st.session_state.role_code:
                    st.error("Please provide role code")
                if not st.session_state.role_name:
                    st.error("Please provide role name")
    
    with col2:
        st.subheader("List Roles")
        
        if st.button("📋 Fetch Roles"):
            url = f"{PROVISIONING_BASE}/provisioning/roles"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} roles")
                
                if response:
                    for role in response:
                        with st.expander(f"🎭 {role.get('name', 'Unknown')} - {role.get('code', 'No code')}", expanded=False):
                            st.json(role)
                else:
                    st.info("No roles found")
            else:
                show_response(status_code, response, "List Roles")

# ===== Vendor Management =====
with tabs[5]:
    st.header("🏪 Vendor Management")
    st.markdown("Create and manage vendors within tenants")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create Vendor")
        
        if st.button("🎲 Generate Vendor ID"):
            st.session_state.vendor_id_input = generate_uuid()
        
        st.text_input("Vendor ID", key="vendor_id_input", value=st.session_state.vendor_id)
        st.text_input("Vendor Name", key="vendor_name", help="Business name of the vendor")
        st.text_input("Contact Email", key="vendor_contact_email")
        st.text_area("Description", key="vendor_description", help="Brief description of vendor's business")
        st.text_input("Tenant ID", key="vendor_tenant_id", value=st.session_state.tenant_id, help="Tenant ID for vendor association")
        
        if st.button("🏪 Create Vendor"):
            if st.session_state.vendor_name:
                # Auto-generate tenant ID if not provided
                tenant_id = st.session_state.vendor_tenant_id or st.session_state.tenant_id
                if not tenant_id:
                    st.error("❌ Please create a tenant first or provide a valid Tenant ID")
                    st.info("💡 Go to the 'Tenant Management' tab to create a tenant first")
                else:
                    vendor_id = st.session_state.vendor_id_input or generate_uuid()
                    url = f"{PROVISIONING_BASE}/provisioning/vendors/{vendor_id}"
                    payload = {
                        "name": st.session_state.vendor_name,
                        "contact_email": st.session_state.vendor_contact_email,
                        "description": st.session_state.vendor_description,
                        "tenant_id": tenant_id
                    }
                    
                    status_code, response = api_call("PUT", url, payload)
                    show_response(status_code, response, "Create Vendor")
                    show_curl("Create Vendor", "PUT", url, payload)
                    
                    if status_code >= 200 and status_code < 300:
                        st.session_state.vendor_id = vendor_id
                        st.rerun()
            else:
                st.error("Please provide vendor name")
    
    with col2:
        st.subheader("List Vendors")
        
        if st.button("📋 Fetch Vendors"):
            url = f"{PROVISIONING_BASE}/provisioning/vendors"
            status_code, response = api_call("GET", url)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} vendors")
                
                if response:
                    for vendor in response:
                        with st.expander(f"🏪 {vendor.get('name', 'Unknown')}", expanded=False):
                            st.json(vendor)
                else:
                    st.info("No vendors found")
            else:
                show_response(status_code, response, "List Vendors")

# ===== Cost Centre Management =====
with tabs[6]:
    st.header("💰 Cost Centre Management")
    st.markdown("Create and manage cost centres for budget tracking")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Create Cost Centre")
        
        st.text_input("Tenant ID", key="cost_centre_tenant_id", value=st.session_state.tenant_id, help="Tenant ID for this cost centre")
        st.text_input("Cost Centre Name", key="cost_centre_name")
        st.number_input("Budget (pence)", key="cost_centre_budget_minor", min_value=0, value=100000, 
                       help="Budget in minor units (100000 = £1000)")
        
        if st.button("💰 Create Cost Centre"):
            if st.session_state.cost_centre_name:
                # Auto-generate tenant ID if not provided
                tenant_id = st.session_state.cost_centre_tenant_id or st.session_state.tenant_id
                if not tenant_id:
                    st.error("❌ Please create a tenant first or provide a valid Tenant ID")
                    st.info("💡 Go to the 'Tenant Management' tab to create a tenant first")
                else:
                    url = f"{PROVISIONING_BASE}/provisioning/cost-centres"
                    payload = {
                        "tenant_id": tenant_id,
                        "name": st.session_state.cost_centre_name,
                        "budget_minor": st.session_state.cost_centre_budget_minor
                    }
                    
                    status_code, response = api_call("POST", url, payload)
                    show_response(status_code, response, "Create Cost Centre")
                    show_curl("Create Cost Centre", "POST", url, payload)
                    
                    if status_code >= 200 and status_code < 300:
                        st.rerun()
            else:
                st.error("Please provide cost centre name")
    
    with col2:
        st.subheader("List Cost Centres")
        
        tenant_filter = st.text_input("Filter by Tenant ID", value=st.session_state.tenant_id, help="Leave empty to list all")
        
        if st.button("📋 Fetch Cost Centres"):
            url = f"{PROVISIONING_BASE}/provisioning/cost-centres"
            params = {}
            if tenant_filter:
                params["tenant_id"] = tenant_filter
            
            status_code, response = api_call("GET", url, params=params)
            
            if status_code >= 200 and status_code < 300 and isinstance(response, list):
                st.success(f"✅ Found {len(response)} cost centres")
                
                if response:
                    for cc in response:
                        budget_gbp = cc.get('budget_minor', 0) / 100
                        spent_gbp = cc.get('spent_minor', 0) / 100
                        with st.expander(f"💰 {cc.get('name', 'Unknown')} - Budget: £{budget_gbp:.2f}", expanded=False):
                            st.json(cc)
                else:
                    st.info("No cost centres found")
            else:
                show_response(status_code, response, "List Cost Centres")

# ===== Browse & Reports =====
with tabs[7]:
    st.header("📊 Browse & Reports")
    st.markdown("Browse all entities and generate reports")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Entity Browser")
        
        entity_choice = st.selectbox("Choose Entity Type", [
            "tenants", "sites", "stores", "users", "roles", "vendors", "cost-centres"
        ])
        
        if st.button("🔍 Browse Entities"):
            url = f"{PROVISIONING_BASE}/provisioning/{entity_choice}"
            status_code, response = api_call("GET", url)
            show_response(status_code, response, f"Browse {entity_choice}")
            
            # Show data in table format if it's a list
            if isinstance(response, list) and response:
                st.subheader(f"📋 {entity_choice.title()} ({len(response)} items)")
                
                for i, item in enumerate(response):
                    with st.expander(f"Item {i+1}: {item.get('name', item.get('code', item.get('email', 'Unknown')))}", expanded=False):
                        st.json(item)
    
    with col2:
        st.subheader("System Health")
        
        if st.button("🏥 Check Service Health"):
            health_status, health_data = check_service_health()
            st.write(f"**Status:** {health_status}")
            if health_data:
                st.json(health_data)
        
        st.subheader("Quick Actions")
        
        st.markdown("""
        **Session Management:**
        - **Clear Session State**: Removes form data but keeps core IDs
        - **Reset All IDs**: Clears all generated IDs for fresh start
        """)
        
        if st.button("🧹 Clear Session State"):
            # Keep core infrastructure IDs but clear form data
            core_ids = ["tenant_id", "site_id", "store_id", "user_id", "role_id", "vendor_id"]
            for key in list(st.session_state.keys()):
                if key not in core_ids:
                    del st.session_state[key]
            st.success("✅ Session state cleared! Core IDs preserved.")
            st.rerun()
        
        if st.button("🔄 Reset All IDs"):
            # Clear ALL IDs - fresh start
            id_keys = ["tenant_id", "site_id", "store_id", "user_id", "role_id", "vendor_id"]
            for key in id_keys:
                if key in st.session_state:
                    st.session_state[key] = ""
            st.success("🔄 All IDs reset! You can now create fresh entities.")
            st.rerun()

# ===== Footer =====
st.markdown("---")
st.markdown("""
**ZeroQue Provisioning Service v4.1.1** - Production-ready with complete saga implementation, outbox pattern, and comprehensive audit logging.

**Features:** Complete CRUD operations for all entities, authentication with API keys, row-level security, subscription limits, and background processing with Celery workers.
""")
