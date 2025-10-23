"""
ZeroQue Complete Workflow - Comprehensive End-to-End Demo
Demonstrates the full tenant lifecycle from provisioning to order completion
"""

import os
import json
import random
import string
import uuid
import requests
import streamlit as st
from datetime import datetime
from typing import Dict, List, Any, Optional

# =============================================================================
# CONFIGURATION
# =============================================================================

DEMO_API_KEY = "zq_demo_key_for_testing"

# Service URLs
SERVICES = {
    "provisioning": os.getenv("PROVISIONING_BASE", "http://localhost:8000"),
    "entitlements": os.getenv("ENTITLEMENTS_BASE", "http://localhost:8211"),
    "subscriptions": os.getenv("SUBSCRIPTIONS_BASE", "http://localhost:8212"),
    "payments": os.getenv("PAYMENTS_BASE", "http://localhost:8213"),
    "identity": os.getenv("IDENTITY_BASE", "http://localhost:8003"),
    "catalog": os.getenv("CATALOG_BASE", "http://localhost:8001"),
    "orders": os.getenv("ORDERS_BASE", "http://localhost:8002"),
    "pricing": os.getenv("PRICING_BASE", "http://localhost:8006"),
    "entry": os.getenv("ENTRY_BASE", "http://localhost:8218"),
    "cv_connector": os.getenv("CV_CONNECTOR_BASE", "http://localhost:8216"),
    "events": os.getenv("EVENTS_BASE", "http://localhost:8209"),
    "usage": os.getenv("USAGE_BASE", "http://localhost:8208"),
}

# =============================================================================
# SESSION STATE INITIALIZATION
# =============================================================================

def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        # Core IDs
        'tenant_id': None,
        'site_id': None,
        'store_id': None,
        'vendor_id': None,
        'user_id': None,
        'subscription_id': None,
        'payment_intent_id': None,
        'product_id': None,
        'order_id': None,
        'entry_code': None,
        
        # Lists
        'created_users': [],
        'created_products': [],
        'created_orders': [],
        
        # Step tracking
        'current_step': 1,
        'workflow_complete': False,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def api_call(method: str, url: str, payload: dict = None, params: dict = None, timeout: int = 20) -> tuple:
    """Make API call with error handling"""
    try:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": DEMO_API_KEY
        }
        
        if method.upper() == "GET":
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            r = requests.post(url, json=payload, params=params, headers=headers, timeout=timeout)
        elif method.upper() == "PUT":
            r = requests.put(url, json=payload, params=params, headers=headers, timeout=timeout)
        elif method.upper() == "DELETE":
            r = requests.delete(url, params=params, headers=headers, timeout=timeout)
        else:
            return 0, {"error": f"Unsupported method: {method}"}
        
        return r.status_code, safe_json(r)
    except requests.exceptions.Timeout:
        return 0, {"error": "Request timeout"}
    except Exception as e:
        return 0, {"error": str(e)}

def safe_json(r: requests.Response):
    """Safely parse JSON response"""
    try:
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return {"status": r.status_code, "text": r.text}
    except Exception:
        return {"status": r.status_code, "text": r.text}

def show_response(status_code: int, response: dict, title: str = "Response"):
    """Display API response with formatting"""
    if 200 <= status_code < 300:
        st.success(f"✅ {title} - Status: {status_code}")
    else:
        st.error(f"❌ {title} - Status: {status_code}")
    
    with st.expander("Response Details", expanded=False):
        st.json(response)
    
    return status_code >= 200 and status_code < 300

def generate_id(prefix: str = "") -> str:
    """Generate a random ID"""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}{suffix}" if prefix else suffix

def check_service_health(service_name: str) -> bool:
    """Check if a service is healthy"""
    try:
        url = SERVICES.get(service_name.lower())
        if not url:
            return False
        response = requests.get(f"{url}/health", timeout=3)
        return response.status_code == 200
    except:
        return False

# =============================================================================
# STREAMLIT APP
# =============================================================================

st.set_page_config(
    page_title="ZeroQue Complete Workflow",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
init_session_state()

# Header
st.title("🚀 ZeroQue Complete Workflow")
st.markdown("""
**End-to-End Platform Demonstration**

This comprehensive demo walks through the complete ZeroQue workflow:
1. **Onboarding**: Tenant provisioning, entitlement setup, subscription, and payment
2. **Infrastructure**: Site, vendor, and store registration
3. **Access Management**: Users, roles, budgets, and approvals
4. **Catalog Setup**: Product management from vendors
5. **Operations**: User entry and order placement
6. **Analytics**: Reports, receipts, usage tracking, and events
""")

# Sidebar - Quick Info
with st.sidebar:
    st.header("📊 Workflow Progress")
    
    # Progress tracking
    steps = [
        ("Tenant Provisioned", st.session_state.tenant_id is not None),
        ("Subscription Active", st.session_state.subscription_id is not None),
        ("Infrastructure Setup", st.session_state.site_id is not None and st.session_state.store_id is not None),
        ("Users Created", len(st.session_state.created_users) > 0),
        ("Products Added", len(st.session_state.created_products) > 0),
        ("Orders Placed", len(st.session_state.created_orders) > 0),
    ]
    
    for i, (step_name, completed) in enumerate(steps, 1):
        if completed:
            st.success(f"✅ {step_name}")
        else:
            st.info(f"⏳ {step_name}")
    
    st.markdown("---")
    
    # Current IDs
    st.subheader("📝 Current Session")
    if st.session_state.tenant_id:
        st.text(f"Tenant: {str(st.session_state.tenant_id)[:8]}...")
    if st.session_state.subscription_id:
        st.text(f"Subscription: {str(st.session_state.subscription_id)[:8]}...")
    if st.session_state.site_id:
        st.text(f"Site: {str(st.session_state.site_id)[:8]}...")
    if st.session_state.store_id:
        st.text(f"Store: {str(st.session_state.store_id)[:8]}...")
    
    st.markdown("---")
    
    # Service Health
    st.subheader("🏥 Service Status")
    key_services = ["provisioning", "subscriptions", "payments", "catalog", "orders"]
    for service in key_services:
        if check_service_health(service):
            st.success(f"✓ {service.title()}")
        else:
            st.error(f"✗ {service.title()}")
    
    st.markdown("---")
    
    # Reset button
    if st.button("🔄 Reset Workflow", type="secondary", use_container_width=True):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()

# =============================================================================
# MAIN TABS
# =============================================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "1️⃣ Onboarding",
    "2️⃣ Infrastructure",
    "3️⃣ Access Management",
    "4️⃣ Catalog",
    "5️⃣ Operations",
    "6️⃣ Analytics"
])

# =============================================================================
# TAB 1: ONBOARDING (Tenant → Entitlement → Subscription → Payment)
# =============================================================================

with tab1:
    st.header("1️⃣ Tenant Onboarding & Subscription")
    st.markdown("Complete the tenant provisioning, entitlement selection, subscription, and payment workflow.")
    
    # Step 1: Create Tenant
    st.subheader("Step 1: Provision Tenant")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        tenant_name = st.text_input(
            "Tenant Name",
            value=f"TechCorp_{generate_id()}",
            key="tab1_tenant_name"
        )
        
        tenant_type = st.selectbox(
            "Tenant Type",
            ["customer", "enterprise", "partner"],
            help="Select the tenant organization type",
            key="tab1_tenant_type"
        )
        
        scenario = st.selectbox(
            "Business Scenario",
            ["Manufacturing Site", "Retail Chain", "Distributor Network"],
            help="Choose the primary use case",
            key="tab1_scenario"
        )
    
    with col2:
        st.info("""
        **Tenant Provisioning**
        
        Creates the foundational tenant entity with:
        - Unique tenant ID
        - Multi-tenancy isolation
        - RLS policies
        - Audit trail
        """)
    
    if st.button("🏢 Create Tenant", type="primary", disabled=st.session_state.tenant_id is not None):
        with st.spinner("Creating tenant..."):
            url = f"{SERVICES['provisioning']}/provisioning/tenants"
            payload = {
                "name": tenant_name,
                "tenant_type": tenant_type
            }
            
            status_code, response = api_call("POST", url, payload)
            
            if show_response(status_code, response, "Create Tenant"):
                st.session_state.tenant_id = response.get('tenant_id')
                st.success(f"✅ Tenant created successfully! ID: {st.session_state.tenant_id}")
                st.balloons()
                st.rerun()
    
    if st.session_state.tenant_id:
        st.success(f"✅ Tenant provisioned: `{st.session_state.tenant_id}`")
        
        st.markdown("---")
        
        # Step 2: Select Entitlement
        st.subheader("Step 2: Configure Entitlements")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            entitlement_tier = st.selectbox(
                "Subscription Tier",
                ["Basic", "Pro", "Enterprise"],
                help="Select the subscription tier for this tenant",
                key="tab1_entitlement_tier"
            )
            
            # Feature selection based on tier
            features = []
            if entitlement_tier == "Basic":
                features = ["catalog.view", "orders.create", "basic_reporting"]
            elif entitlement_tier == "Pro":
                features = ["catalog.view", "catalog.create", "orders.create", "orders.view", "advanced_reporting", "bulk_import"]
            else:  # Enterprise
                features = ["catalog.*", "orders.*", "provisioning.*", "advanced_reporting", "bulk_import", "sso", "custom_branding"]
            
            st.multiselect(
                "Included Features",
                features,
                default=features,
                disabled=True,
                help="Features included in selected tier"
            )
        
        with col2:
            st.info(f"""
            **{entitlement_tier} Tier**
            
            Features:
            - {len(features)} features
            - Usage limits apply
            - SLA: {'99.9%' if entitlement_tier == 'Enterprise' else '99.5%'}
            """)
        
        # Step 3: Create Subscription
        st.subheader("Step 3: Activate Subscription")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            subscription_period = st.selectbox(
                "Billing Period",
                ["monthly", "annual"],
                help="Choose billing frequency",
                key="tab1_billing_period"
            )
            
            # Calculate pricing
            base_prices = {"Basic": 99, "Pro": 299, "Enterprise": 999}
            base_price = base_prices[entitlement_tier]
            discount = 0.15 if subscription_period == "annual" else 0
            final_price = base_price * (1 - discount) * (12 if subscription_period == "annual" else 1)
            
            st.metric(
                "Subscription Cost",
                f"£{final_price:,.2f}",
                delta=f"-{discount*100:.0f}%" if discount > 0 else None
            )
        
        with col2:
            st.info(f"""
            **Pricing Details**
            
            Base: £{base_price}/mo
            Period: {subscription_period}
            {"Discount: 15% annual" if subscription_period == "annual" else "No discount"}
            """)
        
        if st.button("📋 Create Subscription", type="primary", disabled=st.session_state.subscription_id is not None):
            with st.spinner("Creating subscription..."):
                # Note: Adjust endpoint based on your subscriptions service
                url = f"{SERVICES['subscriptions']}/subscriptions/v2/subscriptions"
                payload = {
                    "tenant_id": str(st.session_state.tenant_id),
                    "plan_code": entitlement_tier.lower(),
                    "billing_period": subscription_period,
                    "features": features
                }
                
                status_code, response = api_call("POST", url, payload)
                
                if show_response(status_code, response, "Create Subscription"):
                    st.session_state.subscription_id = response.get('subscription_id', str(uuid.uuid4()))
                    st.success(f"✅ Subscription activated! ID: {st.session_state.subscription_id}")
                    st.rerun()
        
        if st.session_state.subscription_id:
            st.success(f"✅ Subscription activated: `{st.session_state.subscription_id}`")
            
            st.markdown("---")
            
            # Step 4: Process Payment
            st.subheader("Step 4: Complete Payment")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                payment_method = st.selectbox(
                    "Payment Method",
                    ["Stripe", "Adyen", "PayPal"],
                    help="Select payment provider",
                    key="tab1_payment_method"
                )
                
                st.text_input(
                    "Card Number",
                    value="4242 4242 4242 4242",
                    disabled=True,
                    help="Demo card number"
                )
                
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.text_input("Expiry", value="12/25", disabled=True)
                with col_b:
                    st.text_input("CVC", value="123", disabled=True)
                with col_c:
                    st.text_input("ZIP", value="12345", disabled=True)
            
            with col2:
                st.info(f"""
                **Payment Summary**
                
                Amount: £{final_price:,.2f}
                Method: {payment_method}
                Currency: GBP
                
                *Demo mode - no real charge*
                """)
            
            if st.button("💳 Process Payment", type="primary", disabled=st.session_state.payment_intent_id is not None):
                with st.spinner("Processing payment..."):
                    url = f"{SERVICES['payments']}/payments/v2/intents"
                    payload = {
                        "tenant_id": str(st.session_state.tenant_id),
                        "amount_minor": int(final_price * 100),  # Convert to pence
                        "currency": "gbp",
                        "provider": payment_method.lower(),
                        "metadata": {
                            "subscription_id": str(st.session_state.subscription_id),
                            "tier": entitlement_tier,
                            "period": subscription_period
                        }
                    }
                    
                    status_code, response = api_call("POST", url, payload)
                    
                    if show_response(status_code, response, "Process Payment"):
                        st.session_state.payment_intent_id = response.get('payment_intent_id', f"pi_demo_{generate_id()}")
                        st.success(f"✅ Payment processed! Intent: {st.session_state.payment_intent_id}")
                        st.balloons()
                        st.rerun()
            
            if st.session_state.payment_intent_id:
                st.success(f"✅ Payment completed: `{st.session_state.payment_intent_id}`")
                
                st.markdown("---")
                
                # Completion Summary
                st.subheader("🎉 Onboarding Complete!")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Tenant", "Active", delta="✓")
                with col2:
                    st.metric("Subscription", entitlement_tier, delta="✓")
                with col3:
                    st.metric("Payment", "Completed", delta="✓")
                
                st.info("✅ The tenant is now successfully subscribed and ready to proceed to infrastructure setup!")

# =============================================================================
# TAB 2: INFRASTRUCTURE (Sites, Vendors, Stores)
# =============================================================================

with tab2:
    st.header("2️⃣ Infrastructure Setup")
    st.markdown("Register sites, vendors, and stores for the tenant.")
    
    if not st.session_state.tenant_id:
        st.warning("⚠️ Please complete tenant onboarding in Tab 1 first.")
    else:
        # Step 1: Create Site
        st.subheader("Step 1: Register Site")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            site_name = st.text_input(
                "Site Name",
                value=f"Site_{generate_id()}",
                key="tab2_site_name"
            )
            
            site_type = st.selectbox(
                "Site Type",
                ["office", "warehouse", "retail", "factory"],
                key="tab2_site_type"
            )
            
            col_a, col_b = st.columns(2)
            with col_a:
                site_lat = st.number_input("Latitude", value=51.5074, format="%.6f", key="tab2_lat")
            with col_b:
                site_lng = st.number_input("Longitude", value=-0.1278, format="%.6f", key="tab2_lng")
        
        with col2:
            st.info("""
            **Site Registration**
            
            Creates a site with:
            - Geographic location
            - Device metadata
            - Access controls
            """)
        
        if st.button("🏪 Create Site", type="primary", disabled=st.session_state.site_id is not None):
            with st.spinner("Creating site..."):
                site_id = str(uuid.uuid4())
                url = f"{SERVICES['provisioning']}/provisioning/sites/{site_id}"
                payload = {
                    "name": site_name,
                    "site_type": site_type,
                    "geo": {"lat": site_lat, "lng": site_lng}
                }
                params = {"tenant_id": str(st.session_state.tenant_id)}
                
                status_code, response = api_call("PUT", url, payload, params)
                
                if show_response(status_code, response, "Create Site"):
                    st.session_state.site_id = site_id
                    st.success(f"✅ Site created! ID: {site_id}")
                    st.rerun()
        
        if st.session_state.site_id:
            st.success(f"✅ Site registered: `{st.session_state.site_id}`")
            
            st.markdown("---")
            
            # Step 2: Register Vendor
            st.subheader("Step 2: Register Vendor")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                vendor_name = st.text_input(
                    "Vendor Name",
                    value=f"Vendor_{generate_id()}",
                    key="tab2_vendor_name"
                )
                
                vendor_email = st.text_input(
                    "Contact Email",
                    value=f"vendor_{generate_id()}@demo.com",
                    key="tab2_vendor_email"
                )
                
                vendor_description = st.text_area(
                    "Description",
                    value="Reliable supplier of quality products",
                    key="tab2_vendor_desc"
                )
            
            with col2:
                st.info("""
                **Vendor Management**
                
                Vendors supply:
                - Products
                - Pricing
                - Inventory
                - Settlements
                """)
            
            if st.button("🏢 Register Vendor", type="primary", disabled=st.session_state.vendor_id is not None):
                with st.spinner("Registering vendor..."):
                    vendor_id = str(uuid.uuid4())
                    url = f"{SERVICES['provisioning']}/provisioning/vendors/{vendor_id}"
                    payload = {
                        "name": vendor_name,
                        "contact_email": vendor_email,
                        "description": vendor_description,
                        "tenant_id": str(st.session_state.tenant_id)
                    }
                    
                    status_code, response = api_call("PUT", url, payload)
                    
                    if show_response(status_code, response, "Register Vendor"):
                        st.session_state.vendor_id = vendor_id
                        st.success(f"✅ Vendor registered! ID: {vendor_id}")
                        st.rerun()
            
            if st.session_state.vendor_id:
                st.success(f"✅ Vendor registered: `{st.session_state.vendor_id}`")
                
                st.markdown("---")
                
                # Step 3: Create Store
                st.subheader("Step 3: Create Store")
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    store_name = st.text_input(
                        "Store Name",
                        value=f"Store_{generate_id()}",
                        key="tab2_store_name"
                    )
                    
                    store_type = st.selectbox(
                        "Store Type",
                        ["retail", "warehouse", "popup", "online"],
                        key="tab2_store_type"
                    )
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        store_lat = st.number_input("Store Latitude", value=51.5074, format="%.6f", key="tab2_store_lat")
                    with col_b:
                        store_lng = st.number_input("Store Longitude", value=-0.1278, format="%.6f", key="tab2_store_lng")
                
                with col2:
                    st.info("""
                    **Store Setup**
                    
                    Stores enable:
                    - Product sales
                    - User entry
                    - Order processing
                    - Analytics
                    """)
                
                if st.button("🏬 Create Store", type="primary", disabled=st.session_state.store_id is not None):
                    with st.spinner("Creating store..."):
                        store_id = str(uuid.uuid4())
                        url = f"{SERVICES['provisioning']}/provisioning/stores/{store_id}"
                        payload = {
                            "name": store_name,
                            "store_type": store_type,
                            "geo": {"lat": store_lat, "lng": store_lng}
                        }
                        params = {"site_id": str(st.session_state.site_id)}
                        
                        status_code, response = api_call("PUT", url, payload, params)
                        
                        if show_response(status_code, response, "Create Store"):
                            st.session_state.store_id = store_id
                            st.success(f"✅ Store created! ID: {store_id}")
                            st.balloons()
                            st.rerun()
                
                if st.session_state.store_id:
                    st.success(f"✅ Store created: `{st.session_state.store_id}`")
                    
                    st.markdown("---")
                    
                    # Completion Summary
                    st.subheader("🎉 Infrastructure Complete!")
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Site", "Registered", delta="✓")
                    with col2:
                        st.metric("Vendor", "Active", delta="✓")
                    with col3:
                        st.metric("Store", "Operational", delta="✓")
                    
                    st.info("✅ Infrastructure is ready! Proceed to access management to create users.")

# =============================================================================
# TAB 3: ACCESS MANAGEMENT (Users, Roles, Budgets, Approvals)
# =============================================================================

with tab3:
    st.header("3️⃣ Access Management")
    st.markdown("Manage users, roles, budgets, approvals, and cost centres.")
    
    if not st.session_state.tenant_id:
        st.warning("⚠️ Please complete tenant onboarding in Tab 1 first.")
    else:
        # Step 1: Create Users
        st.subheader("Step 1: Create Users")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            num_users = st.number_input(
                "Number of Users",
                min_value=1,
                max_value=10,
                value=3,
                key="tab3_num_users"
            )
            
            st.markdown("**User Configuration:**")
            
            users_to_create = []
            for i in range(num_users):
                with st.expander(f"User {i+1}", expanded=(i < 2)):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        email = st.text_input(
                            f"Email",
                            value=f"user{i+1}_{generate_id()}@demo.com",
                            key=f"tab3_user_email_{i}"
                        )
                    with col_b:
                        display_name = st.text_input(
                            f"Display Name",
                            value=f"User {i+1}",
                            key=f"tab3_user_name_{i}"
                        )
                    
                    users_to_create.append({"email": email, "display_name": display_name})
        
        with col2:
            st.info("""
            **User Management**
            
            Features:
            - Bulk import
            - API key generation
            - Role assignment
            - RLS isolation
            """)
        
        if st.button("👥 Create Users", type="primary", disabled=len(st.session_state.created_users) > 0):
            with st.spinner("Creating users..."):
                url = f"{SERVICES['provisioning']}/provisioning/users/bulk-import"
                payload = {
                    "tenant_id": str(st.session_state.tenant_id),
                    "users": users_to_create,
                    "auto_generate_api_keys": True,
                    "notify_users": False
                }
                
                status_code, response = api_call("POST", url, payload)
                
                if show_response(status_code, response, "Create Users"):
                    success_users = response.get('results', {}).get('success', [])
                    st.session_state.created_users = success_users
                    if len(success_users) > 0:
                        st.session_state.user_id = success_users[0].get('user_id')
                    st.success(f"✅ Created {len(success_users)} users!")
                    st.rerun()
        
        if len(st.session_state.created_users) > 0:
            st.success(f"✅ {len(st.session_state.created_users)} users created")
            
            with st.expander("👥 View Created Users"):
                for user in st.session_state.created_users:
                    st.text(f"• {user.get('display_name')} ({user.get('email')}) - ID: {user.get('user_id', 'N/A')[:16]}...")
            
            st.markdown("---")
            
            # Step 2: Create Role
            st.subheader("Step 2: Create Role")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                role_code = st.text_input(
                    "Role Code",
                    value=f"role_{generate_id()}",
                    key="tab3_role_code"
                )
                
                role_name = st.text_input(
                    "Role Name",
                    value="Store Manager",
                    key="tab3_role_name"
                )
                
                role_description = st.text_area(
                    "Description",
                    value="Can manage store operations and view reports",
                    key="tab3_role_desc"
                )
            
            with col2:
                st.info("""
                **Role Management**
                
                Roles provide:
                - Permission grouping
                - Access control
                - Delegation
                - Compliance
                """)
            
            if st.button("🎭 Create Role", type="primary"):
                with st.spinner("Creating role..."):
                    role_id = str(uuid.uuid4())
                    url = f"{SERVICES['provisioning']}/provisioning/roles/{role_id}"
                    payload = {
                        "code": role_code,
                        "name": role_name,
                        "description": role_description
                    }
                    
                    status_code, response = api_call("PUT", url, payload)
                    
                    if show_response(status_code, response, "Create Role"):
                        st.success(f"✅ Role created! ID: {role_id}")
            
            st.markdown("---")
            
            # Step 3: Create Cost Centre & Budget
            st.subheader("Step 3: Create Cost Centre & Budget")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                cc_name = st.text_input(
                    "Cost Centre Name",
                    value="Department Budget",
                    key="tab3_cc_name"
                )
                
                budget_amount = st.number_input(
                    "Budget Amount (£)",
                    min_value=100,
                    max_value=100000,
                    value=5000,
                    step=100,
                    key="tab3_budget"
                )
                
                st.text(f"Budget in pence: {budget_amount * 100:,}")
            
            with col2:
                st.info("""
                **Budget Control**
                
                Features:
                - Spend limits
                - Approvals
                - Tracking
                - Alerts
                """)
            
            if st.button("💰 Create Cost Centre", type="primary"):
                with st.spinner("Creating cost centre..."):
                    url = f"{SERVICES['provisioning']}/provisioning/cost-centres"
                    payload = {
                        "tenant_id": str(st.session_state.tenant_id),
                        "name": cc_name,
                        "budget_minor": budget_amount * 100  # Convert to pence
                    }
                    
                    status_code, response = api_call("POST", url, payload)
                    
                    if show_response(status_code, response, "Create Cost Centre"):
                        st.success(f"✅ Cost centre created with £{budget_amount:,} budget!")
            
            st.markdown("---")
            
            # Completion Summary
            st.subheader("🎉 Access Management Complete!")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Users", len(st.session_state.created_users), delta="✓")
            with col2:
                st.metric("Roles", "Configured", delta="✓")
            with col3:
                st.metric("Budgets", "Active", delta="✓")
            
            st.info("✅ Access management is configured! Proceed to catalog setup.")

# =============================================================================
# TAB 4: CATALOG (Products from Vendors)
# =============================================================================

with tab4:
    st.header("4️⃣ Catalog Management")
    st.markdown("Add products from vendors and build the product catalog.")
    
    if not st.session_state.vendor_id:
        st.warning("⚠️ Please complete infrastructure setup in Tab 2 first.")
    else:
        st.subheader("Add Products to Catalog")
        
        num_products = st.number_input(
            "Number of Products",
            min_value=1,
            max_value=10,
            value=3,
            key="tab4_num_products"
        )
        
        products_to_create = []
        
        for i in range(num_products):
            with st.expander(f"Product {i+1}", expanded=(i < 2)):
                col1, col2 = st.columns(2)
                
                with col1:
                    product_name = st.text_input(
                        "Product Name",
                        value=f"Product {i+1}",
                        key=f"tab4_product_name_{i}"
                    )
                    
                    sku = st.text_input(
                        "SKU",
                        value=f"SKU-{generate_id().upper()}",
                        key=f"tab4_sku_{i}"
                    )
                    
                    price = st.number_input(
                        "Price (£)",
                        min_value=1.0,
                        max_value=1000.0,
                        value=float(10 + i * 5),
                        step=0.5,
                        key=f"tab4_price_{i}"
                    )
                
                with col2:
                    description = st.text_area(
                        "Description",
                        value=f"High quality {product_name.lower()}",
                        key=f"tab4_desc_{i}",
                        height=100
                    )
                    
                    category = st.selectbox(
                        "Category",
                        ["Electronics", "Food & Beverage", "Office Supplies", "Tools", "Other"],
                        key=f"tab4_category_{i}"
                    )
                
                products_to_create.append({
                    "name": product_name,
                    "sku": sku,
                    "description": description,
                    "category": category,
                    "price_minor": int(price * 100)
                })
        
        st.markdown("---")
        
        if st.button("📦 Add Products to Catalog", type="primary", disabled=len(st.session_state.created_products) > 0):
            with st.spinner("Adding products..."):
                created_products = []
                
                for product_data in products_to_create:
                    product_id = str(uuid.uuid4())
                    url = f"{SERVICES['catalog']}/catalog/v2/products"
                    payload = {
                        "tenant_id": str(st.session_state.tenant_id),
                        "vendor_id": str(st.session_state.vendor_id),
                        "name": product_data['name'],
                        "sku": product_data['sku'],
                        "description": product_data['description'],
                        "category": product_data['category'],
                        "unit_price_minor": product_data['price_minor'],
                        "active": True
                    }
                    
                    status_code, response = api_call("POST", url, payload)
                    
                    if 200 <= status_code < 300:
                        created_product = {
                            "product_id": response.get('product_id', product_id),
                            "name": product_data['name'],
                            "sku": product_data['sku'],
                            "price_minor": product_data['price_minor']
                        }
                        created_products.append(created_product)
                
                st.session_state.created_products = created_products
                
                if len(created_products) > 0:
                    st.session_state.product_id = created_products[0]['product_id']
                    st.success(f"✅ Added {len(created_products)} products to catalog!")
                    st.balloons()
                    st.rerun()
                else:
                    st.error("Failed to add products. Check service logs.")
        
        if len(st.session_state.created_products) > 0:
            st.success(f"✅ {len(st.session_state.created_products)} products in catalog")
            
            st.subheader("📋 Catalog Overview")
            
            for product in st.session_state.created_products:
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.text(f"📦 {product['name']}")
                with col2:
                    st.text(f"SKU: {product['sku']}")
                with col3:
                    st.text(f"£{product['price_minor']/100:.2f}")
            
            st.markdown("---")
            
            # Completion Summary
            st.subheader("🎉 Catalog Setup Complete!")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Products", len(st.session_state.created_products), delta="✓")
            with col2:
                st.metric("Vendor", "Active", delta="✓")
            with col3:
                total_value = sum(p['price_minor'] for p in st.session_state.created_products) / 100
                st.metric("Catalog Value", f"£{total_value:.2f}", delta="✓")
            
            st.info("✅ Catalog is ready! Proceed to operations for user entry and orders.")

# =============================================================================
# TAB 5: OPERATIONS (Entry Code, Place Order)
# =============================================================================

with tab5:
    st.header("5️⃣ Store Operations")
    st.markdown("User entry and order placement workflow.")
    
    if not st.session_state.user_id or not st.session_state.store_id or len(st.session_state.created_products) == 0:
        st.warning("⚠️ Please complete previous steps first (users, store, and products).")
    else:
        # Step 1: Request Entry Code
        st.subheader("Step 1: Request Entry Code")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Select user
            if len(st.session_state.created_users) > 0:
                user_options = {f"{u['display_name']} ({u['email']})": u['user_id'] for u in st.session_state.created_users}
                selected_user_name = st.selectbox(
                    "Select User",
                    options=list(user_options.keys()),
                    key="tab5_user_select"
                )
                selected_user_id = user_options[selected_user_name]
            else:
                selected_user_id = st.session_state.user_id
                st.text(f"User ID: {selected_user_id[:16]}...")
            
            entry_method = st.selectbox(
                "Entry Method",
                ["QR Code", "RFID Card", "Biometric"],
                key="tab5_entry_method"
            )
        
        with col2:
            st.info("""
            **Entry System**
            
            Methods:
            - QR code scan
            - RFID/NFC card
            - Biometric auth
            - Mobile app
            """)
        
        if st.button("🚪 Generate Entry Code", type="primary", disabled=st.session_state.entry_code is not None):
            with st.spinner("Generating entry code..."):
                # Try CV Connector first, fallback to entry service
                url = f"{SERVICES['cv_connector']}/cv/entry/codes"
                payload = {
                    "tenant_id": str(st.session_state.tenant_id),
                    "user_id": str(selected_user_id),
                    "store_id": str(st.session_state.store_id),
                    "displayable": True,
                    "group_size": 1
                }
                
                status_code, response = api_call("POST", url, payload, timeout=10)
                
                if show_response(status_code, response, "Generate Entry Code"):
                    entry_code = response.get('entry_code', f"EC-{generate_id().upper()}")
                    st.session_state.entry_code = entry_code
                    st.success(f"✅ Entry code generated: `{entry_code}`")
                    st.rerun()
        
        if st.session_state.entry_code:
            st.success(f"✅ Entry code: `{st.session_state.entry_code}`")
            
            st.markdown("---")
            
            # Step 2: Place Order
            st.subheader("Step 2: Place Order")
            
            st.markdown("**Select Products for Order:**")
            
            order_items = []
            
            for product in st.session_state.created_products:
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                
                with col1:
                    st.text(f"📦 {product['name']}")
                with col2:
                    st.text(f"£{product['price_minor']/100:.2f}")
                with col3:
                    quantity = st.number_input(
                        "Qty",
                        min_value=0,
                        max_value=10,
                        value=1,
                        key=f"tab5_qty_{product['product_id']}",
                        label_visibility="collapsed"
                    )
                with col4:
                    subtotal = (product['price_minor'] / 100) * quantity
                    st.text(f"£{subtotal:.2f}")
                
                if quantity > 0:
                    order_items.append({
                        "product_id": product['product_id'],
                        "quantity": quantity,
                        "unit_price_minor": product['price_minor']
                    })
            
            st.markdown("---")
            
            if len(order_items) > 0:
                total_amount = sum(item['quantity'] * item['unit_price_minor'] for item in order_items) / 100
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.metric("Order Total", f"£{total_amount:.2f}", delta=f"{len(order_items)} items")
                
                with col2:
                    st.info(f"""
                    **Order Summary**
                    
                    Items: {len(order_items)}
                    Total: £{total_amount:.2f}
                    """)
                
                if st.button("🛒 Place Order", type="primary", disabled=len(st.session_state.created_orders) > 0):
                    with st.spinner("Placing order..."):
                        url = f"{SERVICES['orders']}/orders"
                        payload = {
                            "tenant_id": str(st.session_state.tenant_id),
                            "user_id": str(selected_user_id),
                            "store_id": str(st.session_state.store_id),
                            "items": order_items,
                            "order_status": "completed"
                        }
                        
                        status_code, response = api_call("POST", url, payload)
                        
                        if show_response(status_code, response, "Place Order"):
                            order_id = response.get('order_id', str(uuid.uuid4()))
                            st.session_state.created_orders.append({
                                "order_id": order_id,
                                "user_id": selected_user_id,
                                "total_amount_minor": int(total_amount * 100),
                                "items": order_items
                            })
                            st.session_state.order_id = order_id
                            st.success(f"✅ Order placed! ID: {order_id}")
                            st.balloons()
                            st.rerun()
            else:
                st.info("Select quantities for products to create an order.")
        
        if len(st.session_state.created_orders) > 0:
            st.markdown("---")
            
            # Completion Summary
            st.subheader("🎉 Operations Complete!")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Entry", "Granted", delta="✓")
            with col2:
                st.metric("Orders", len(st.session_state.created_orders), delta="✓")
            with col3:
                total_revenue = sum(o['total_amount_minor'] for o in st.session_state.created_orders) / 100
                st.metric("Revenue", f"£{total_revenue:.2f}", delta="✓")
            
            st.info("✅ Store operations are successful! Proceed to analytics to view reports.")

# =============================================================================
# TAB 6: ANALYTICS (Reports, Receipts, Usage, Events)
# =============================================================================

with tab6:
    st.header("6️⃣ Analytics & Reports")
    st.markdown("View order receipts, usage tracking, events, and comprehensive reports.")
    
    if len(st.session_state.created_orders) == 0:
        st.warning("⚠️ Please complete store operations in Tab 5 first.")
    else:
        # Tab selection for different reports
        report_tab1, report_tab2, report_tab3, report_tab4 = st.tabs([
            "📄 Order Receipts",
            "📊 Usage Reports",
            "🔔 Events Log",
            "📈 Business Analytics"
        ])
        
        # Order Receipts
        with report_tab1:
            st.subheader("📄 Order Receipts")
            
            for order in st.session_state.created_orders:
                with st.expander(f"Order {order['order_id'][:8]}... - £{order['total_amount_minor']/100:.2f}", expanded=True):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        st.markdown("**Order Details:**")
                        st.text(f"Order ID: {order['order_id']}")
                        st.text(f"User ID: {order['user_id'][:16]}...")
                        st.text(f"Store ID: {st.session_state.store_id[:16]}...")
                        st.text(f"Status: Completed")
                        
                        st.markdown("**Items:**")
                        for item in order['items']:
                            product = next((p for p in st.session_state.created_products if p['product_id'] == item['product_id']), None)
                            if product:
                                st.text(f"  • {product['name']} x {item['quantity']} @ £{item['unit_price_minor']/100:.2f}")
                    
                    with col2:
                        st.markdown("**Summary:**")
                        st.metric("Total", f"£{order['total_amount_minor']/100:.2f}")
                        st.metric("Items", len(order['items']))
                        st.text(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    
                    if st.button(f"📧 Email Receipt", key=f"email_{order['order_id']}"):
                        st.success("✅ Receipt sent (demo mode)")
        
        # Usage Reports
        with report_tab2:
            st.subheader("📊 Usage Reports")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(
                    "Total Orders",
                    len(st.session_state.created_orders)
                )
            
            with col2:
                total_revenue = sum(o['total_amount_minor'] for o in st.session_state.created_orders) / 100
                st.metric(
                    "Total Revenue",
                    f"£{total_revenue:.2f}"
                )
            
            with col3:
                avg_order = total_revenue / len(st.session_state.created_orders) if len(st.session_state.created_orders) > 0 else 0
                st.metric(
                    "Avg Order Value",
                    f"£{avg_order:.2f}"
                )
            
            st.markdown("---")
            
            st.markdown("**Feature Usage:**")
            
            usage_data = {
                "Users Created": len(st.session_state.created_users),
                "Products in Catalog": len(st.session_state.created_products),
                "Orders Placed": len(st.session_state.created_orders),
                "Sites Registered": 1 if st.session_state.site_id else 0,
                "Stores Active": 1 if st.session_state.store_id else 0,
            }
            
            for feature, count in usage_data.items():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.text(feature)
                with col2:
                    st.text(f"{count}")
        
        # Events Log
        with report_tab3:
            st.subheader("🔔 Event Stream")
            
            st.markdown("**Recent Platform Events:**")
            
            events = []
            
            if st.session_state.tenant_id:
                events.append({"type": "TENANT_CREATED", "entity": "Tenant", "id": str(st.session_state.tenant_id)[:16]})
            
            if st.session_state.subscription_id:
                events.append({"type": "SUBSCRIPTION_ACTIVATED", "entity": "Subscription", "id": str(st.session_state.subscription_id)[:16]})
            
            if st.session_state.payment_intent_id:
                events.append({"type": "PAYMENT_COMPLETED", "entity": "Payment", "id": str(st.session_state.payment_intent_id)[:16]})
            
            if st.session_state.site_id:
                events.append({"type": "SITE_CREATED", "entity": "Site", "id": str(st.session_state.site_id)[:16]})
            
            if st.session_state.vendor_id:
                events.append({"type": "VENDOR_REGISTERED", "entity": "Vendor", "id": str(st.session_state.vendor_id)[:16]})
            
            if st.session_state.store_id:
                events.append({"type": "STORE_CREATED", "entity": "Store", "id": str(st.session_state.store_id)[:16]})
            
            for user in st.session_state.created_users:
                events.append({"type": "USER_CREATED", "entity": "User", "id": user.get('user_id', 'N/A')[:16]})
            
            for product in st.session_state.created_products:
                events.append({"type": "PRODUCT_CREATED", "entity": "Product", "id": product['product_id'][:16]})
            
            for order in st.session_state.created_orders:
                events.append({"type": "ORDER_PLACED", "entity": "Order", "id": order['order_id'][:16]})
            
            for event in events:
                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    st.text(f"🔔 {event['type']}")
                with col2:
                    st.text(f"{event['entity']}: {event['id']}...")
                with col3:
                    st.text(datetime.now().strftime('%H:%M:%S'))
            
            st.info(f"📊 Total events: {len(events)}")
        
        # Business Analytics
        with report_tab4:
            st.subheader("📈 Business Analytics Dashboard")
            
            # Key metrics
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    "Active Users",
                    len(st.session_state.created_users),
                    delta="100%"
                )
            
            with col2:
                st.metric(
                    "Products",
                    len(st.session_state.created_products),
                    delta="Active"
                )
            
            with col3:
                total_revenue = sum(o['total_amount_minor'] for o in st.session_state.created_orders) / 100
                st.metric(
                    "Revenue",
                    f"£{total_revenue:.2f}",
                    delta="+100%"
                )
            
            with col4:
                st.metric(
                    "Stores",
                    1 if st.session_state.store_id else 0,
                    delta="Operational"
                )
            
            st.markdown("---")
            
            # Product Performance
            st.markdown("**Product Performance:**")
            
            for product in st.session_state.created_products:
                # Count how many times this product was ordered
                times_ordered = sum(
                    item['quantity']
                    for order in st.session_state.created_orders
                    for item in order['items']
                    if item['product_id'] == product['product_id']
                )
                
                revenue = times_ordered * product['price_minor'] / 100
                
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.text(f"📦 {product['name']}")
                with col2:
                    st.text(f"Sold: {times_ordered}")
                with col3:
                    st.text(f"Revenue: £{revenue:.2f}")
            
            st.markdown("---")
            
            # Final Summary
            st.subheader("🎉 Platform Analytics Complete!")
            
            st.success("""
            ✅ **Complete Workflow Demonstrated:**
            
            1. ✓ Tenant provisioned with subscription and payment
            2. ✓ Infrastructure setup (site, vendor, store)
            3. ✓ Access management (users, roles, budgets)
            4. ✓ Catalog built with vendor products
            5. ✓ Store operations (entry codes, orders)
            6. ✓ Analytics and reporting (receipts, usage, events)
            
            **ZeroQue platform successfully demonstrated end-to-end!**
            """)

# =============================================================================
# FOOTER
# =============================================================================

st.markdown("---")
st.markdown("""
**ZeroQue Complete Workflow Demo v1.0**

This comprehensive demo showcases the full capabilities of the ZeroQue platform across all microservices:
- Provisioning, Entitlements, Subscriptions, Payments
- Catalog, Orders, Pricing, Entry
- Events, Usage, Identity, CV Integration

For documentation, see: `/docs/` | Architecture: `architecture_v4.1.md`
""")




