"""
ZeroQue V4.1 - Phase 1 & 2 Features Dashboard
Professional testing interface for Identity & Access and Sites & Hardware features
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime

# Configuration
API_KEY = "zq_demo_key_for_testing"
PROVISIONING_URL = "http://localhost:8000"
IDENTITY_URL = "http://localhost:8003"
CV_CONNECTOR_URL = "http://localhost:8216"
CV_GATEWAY_URL = "http://localhost:8215"
ENTRY_URL = "http://localhost:8218"  # Entry service

# Initialize session state
if 'tenant_id' not in st.session_state:
    st.session_state.tenant_id = None
if 'site_id' not in st.session_state:
    st.session_state.site_id = None
if 'store_id' not in st.session_state:
    st.session_state.store_id = None
if 'user_ids' not in st.session_state:
    st.session_state.user_ids = []

# Page config
st.set_page_config(
    page_title="ZeroQue Phase 1 & 2 Features",
    page_icon="⚡",
    layout="wide"
)

# Title
st.title("ZeroQue V4.1 - Phase 1 & 2 Features Dashboard")
st.markdown("Professional testing interface for new features")

# Sidebar - Setup Section
st.sidebar.header("Quick Setup")

# Create Tenant Button
if st.sidebar.button("Create New Tenant", type="primary"):
    tenant_name = f"TestCorp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        response = requests.post(
            f"{PROVISIONING_URL}/provisioning/tenants",
            headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
            json={"name": tenant_name, "tenant_type": "enterprise"}
        )
        if response.status_code == 200:
            result = response.json()
            st.session_state.tenant_id = result['tenant_id']
            st.sidebar.success(f"Tenant created: {result['tenant_id'][:8]}...")
        else:
            st.sidebar.error(f"Failed: {response.text[:100]}")
    except Exception as e:
        st.sidebar.error(f"Error: {str(e)[:100]}")

# Display current tenant
if st.session_state.tenant_id:
    st.sidebar.info(f"Current Tenant: {st.session_state.tenant_id[:8]}...")
    
    # Create Site Button
    if st.sidebar.button("Create Test Site"):
        try:
            site_id = str(uuid.uuid4())
            response = requests.put(
                f"{PROVISIONING_URL}/provisioning/sites/{site_id}",
                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                params={"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa"},
                json={
                    "name": f"Site_{datetime.now().strftime('%H%M%S')}",
                    "site_type": "retail",
                    "device_metadata": {
                        "cameras": [{"id": "cam-01", "type": "overhead", "zone": "checkout"}],
                        "sensors": [{"id": "sensor-01", "type": "motion", "zone": "entry"}],
                        "entry_devices": [{"id": "entry-01", "type": "rfid_reader"}]
                    }
                }
            )
            if response.status_code == 200:
                st.session_state.site_id = site_id
                st.sidebar.success(f"Site created: {site_id[:8]}...")
            else:
                st.sidebar.error(f"Failed: {response.text[:100]}")
        except Exception as e:
            st.sidebar.error(f"Error: {str(e)[:100]}")
    
    # Create Store Button
    if st.session_state.site_id and st.sidebar.button("Create Test Store"):
        try:
            store_id = str(uuid.uuid4())
            response = requests.put(
                f"{PROVISIONING_URL}/provisioning/stores/{store_id}",
                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                params={"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa", "site_id": st.session_state.site_id},
                json={"name": f"Store_{datetime.now().strftime('%H%M%S')}", "store_type": "retail"}
            )
            if response.status_code == 200:
                st.session_state.store_id = store_id
                st.sidebar.success(f"Store created: {store_id[:8]}...")
            else:
                st.sidebar.error(f"Failed: {response.text[:100]}")
        except Exception as e:
            st.sidebar.error(f"Error: {str(e)[:100]}")
    
    if st.session_state.site_id:
        st.sidebar.info(f"Site: {st.session_state.site_id[:8]}...")
    if st.session_state.store_id:
        st.sidebar.info(f"Store: {st.session_state.store_id[:8]}...")
else:
    st.sidebar.warning("Click 'Create New Tenant' to start")

st.sidebar.markdown("---")

# Tab layout
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Bulk User Import",
    "OAuth/SSO Configuration",
    "Entry Methods",
    "Site & Device Registry",
    "Device Monitoring"
])

# ============================================
# TAB 1: BULK USER IMPORT
# ============================================
with tab1:
    st.header("Bulk User Import (Pro/Enterprise Feature)")
    
    if not st.session_state.tenant_id:
        st.warning("Please create a tenant first using the sidebar.")
    else:
        st.markdown(f"**Current Tenant**: `{st.session_state.tenant_id}`")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("User List")
            
            num_users = st.number_input("Number of Users", min_value=1, max_value=20, value=3)
            
            users = []
            for i in range(num_users):
                with st.expander(f"User {i+1}", expanded=(i<2)):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        email = st.text_input(
                            "Email",
                            key=f"email_{i}",
                            value=f"user{i+1}_{datetime.now().strftime('%H%M%S')}@test.com"
                        )
                    with col_b:
                        display_name = st.text_input(
                            "Display Name",
                            key=f"name_{i}",
                            value=f"User {i+1}"
                        )
                    
                    permissions = st.multiselect(
                        "Permissions",
                        ["catalog.view", "catalog.create", "orders.view", "orders.create"],
                        key=f"perms_{i}"
                    )
                    
                    users.append({
                        "email": email,
                        "display_name": display_name,
                        "permissions": permissions
                    })
            
            auto_api_keys = st.checkbox("Auto-generate API keys", value=True)
            
            if st.button("Import Users", type="primary", use_container_width=True):
                with st.spinner("Importing users..."):
                    try:
                        response = requests.post(
                            f"{PROVISIONING_URL}/provisioning/users/bulk-import",
                            headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                            json={
                                "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                "users": users,
                                "auto_generate_api_keys": auto_api_keys,
                                "notify_users": False
                            }
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            st.success(f"Import complete: {result['success_count']}/{result['total_requested']} users created")
                            
                            # Store user IDs
                            st.session_state.user_ids = [u['user_id'] for u in result['results']['success']]
                            
                            st.subheader("Results")
                            
                            if result['results']['success']:
                                st.markdown("**Successful:**")
                                for user in result['results']['success']:
                                    with st.expander(f"{user['email']}"):
                                        st.code(f"User ID: {user['user_id']}\nEmail: {user['email']}\nAPI Key: {user.get('api_key', 'N/A')}")
                            
                            if result['results']['failed']:
                                st.markdown("**Failed:**")
                                for failed in result['results']['failed']:
                                    st.error(f"{failed.get('email', 'unknown')}: {failed.get('error', 'Unknown error')}")
                        else:
                            st.error(f"Import failed: {response.text}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        with col2:
            st.subheader("Feature Information")
            st.info("""
            **Self-Service User Provisioning**
            
            - Tier: Pro/Enterprise
            - Permission: provisioning.bulk_import
            - Limit: Based on subscription
            
            Features:
            - Bulk import multiple users
            - Auto-generate API keys
            - Permission assignment
            - Transactional safety (Saga pattern)
            
            Events:
            - Publishes USER_CREATED for each user
            - CV Connector syncs users to AiFi
            """)

# ============================================
# TAB 2: OAUTH/SSO
# ============================================
with tab2:
    st.header("OAuth/SSO Configuration (Pro/Enterprise Feature)")
    
    if not st.session_state.tenant_id:
        st.warning("Please create a tenant first using the sidebar.")
    else:
        st.markdown(f"**Current Tenant**: `{st.session_state.tenant_id}`")
        
        sub_tab1, sub_tab2, sub_tab3 = st.tabs(["Create Provider", "List Providers", "Initiate Flow"])
        
        with sub_tab1:
            st.subheader("Create OAuth Provider")
            
            col1, col2 = st.columns(2)
            
            with col1:
                provider_type = st.selectbox("Provider Type", ["azure_ad", "google", "okta", "auth0"])
                provider_name = st.text_input("Provider Name", value="Company SSO")
                client_id = st.text_input("Client ID", value="test-client-id")
            
            with col2:
                client_secret = st.text_input("Client Secret", type="password", value="test-client-secret")
                
                if provider_type == "azure_ad":
                    tenant_domain = st.text_input("Tenant Domain", value="company.onmicrosoft.com")
                else:
                    tenant_domain = None
                
                discovery_url = st.text_input("Discovery URL (optional)", value="")
            
            scopes = st.multiselect(
                "Scopes",
                ["openid", "profile", "email", "address", "phone"],
                default=["openid", "profile", "email"]
            )
            
            if st.button("Create OAuth Provider", type="primary"):
                with st.spinner("Creating provider..."):
                    try:
                        payload = {
                            "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                            "provider_type": provider_type,
                            "provider_name": provider_name,
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "scopes": scopes
                        }
                        
                        if tenant_domain:
                            payload["tenant_domain"] = tenant_domain
                        if discovery_url:
                            payload["discovery_url"] = discovery_url
                        
                        response = requests.post(
                            f"{IDENTITY_URL}/identity/v4/oauth/providers",
                            headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                            json=payload,
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            st.success(f"Provider created! ID: {result['provider_id']}")
                            st.json(result)
                        else:
                            st.error(f"Failed ({response.status_code}): {response.text}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection error: {str(e)}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        with sub_tab2:
            st.subheader("List OAuth Providers")
            
            if st.button("Refresh Providers"):
                with st.spinner("Loading providers..."):
                    try:
                        response = requests.get(
                            f"{IDENTITY_URL}/identity/v4/oauth/providers",
                            headers={"x-api-key": API_KEY},
                            params={"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa"},
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            providers = result.get("providers", [])
                            
                            if providers:
                                st.success(f"Found {len(providers)} provider(s)")
                                for provider in providers:
                                    with st.expander(f"{provider['provider_name']} ({provider['provider_type']})"):
                                        st.json(provider)
                            else:
                                st.info("No OAuth providers configured yet")
                        else:
                            st.error(f"Failed ({response.status_code}): {response.text}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection error: {str(e)}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        with sub_tab3:
            st.subheader("Initiate OAuth Flow")
            st.info("This demonstrates OAuth flow initiation. In production, users would be redirected to the authorization URL.")
            
            provider_id = st.text_input("Provider ID", placeholder="Enter provider UUID from List tab")
            redirect_uri = st.text_input("Redirect URI", value="https://app.company.com/auth/callback")
            
            if st.button("Initiate OAuth Flow"):
                if not provider_id:
                    st.warning("Please enter a Provider ID")
                else:
                    with st.spinner("Initiating OAuth flow..."):
                        try:
                            response = requests.post(
                                f"{IDENTITY_URL}/identity/v4/oauth/initiate",
                                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                json={
                                    "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                    "provider_id": provider_id,
                                    "redirect_uri": redirect_uri
                                },
                                timeout=10
                            )
                            
                            if response.status_code == 200:
                                result = response.json()
                                st.success("OAuth flow initiated!")
                                st.markdown("**Authorization URL:**")
                                st.code(result['authorization_url'])
                                st.markdown("**State:**")
                                st.code(result['state'])
                                st.json(result)
                            else:
                                st.error(f"Failed ({response.status_code}): {response.text}")
                        except requests.exceptions.RequestException as e:
                            st.error(f"Connection error: {str(e)}")
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

# ============================================
# TAB 3: ENTRY METHODS
# ============================================
with tab3:
    st.header("Entry Methods (QR, Card, Biometric)")
    
    if not st.session_state.tenant_id or not st.session_state.user_ids:
        st.warning("Please create a tenant and import users first.")
    else:
        st.markdown(f"**Tenant**: `{st.session_state.tenant_id[:16]}...`")
        
        # User selection
        user_id = st.selectbox(
            "Select User",
            st.session_state.user_ids,
            format_func=lambda x: x[:16] + "..."
        ) if st.session_state.user_ids else st.text_input("User ID", value=str(uuid.uuid4()))
        
        entry_tab1, entry_tab2, entry_tab3 = st.tabs(["QR Entry", "Card Entry", "Biometric Entry"])
        
        with entry_tab1:
            st.subheader("QR Code Entry")
            st.markdown("Generate QR code for store entry")
            
            qr_service = st.radio(
                "Entry Service",
                ["CV Connector (AiFi)", "Entry Service (ZeroQue)"],
                help="We have 2 entry code generation methods"
            )
            
            if st.button("Generate QR Code"):
                with st.spinner("Generating QR code..."):
                    try:
                        if qr_service == "CV Connector (AiFi)":
                            # Use CV Connector /cv/entry/codes endpoint
                            response = requests.post(
                                f"{CV_CONNECTOR_URL}/cv/entry/codes",
                                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                json={
                                    "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                    "user_id": user_id,
                                    "displayable": True,
                                    "group_size": 1
                                },
                                timeout=10
                            )
                        else:
                            # Use Entry Service - handle gracefully if not available
                            try:
                                response = requests.post(
                                    f"{ENTRY_URL}/entry/codes",
                                    headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                    json={
                                        "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                        "user_id": user_id,
                                        "displayable": True
                                    },
                                    timeout=5
                                )
                            except requests.exceptions.ConnectionError:
                                st.warning("⚠️ Entry service not available. Using CV Connector as fallback.")
                                response = requests.post(
                                    f"{CV_CONNECTOR_URL}/cv/entry/codes",
                                    headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                    json={
                                        "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                        "user_id": user_id,
                                        "displayable": True,
                                        "group_size": 1
                                    },
                                    timeout=10
                                )
                        
                        if response.status_code == 200:
                            result = response.json()
                            st.success("QR code generated successfully!")
                            st.json(result)
                        else:
                            st.error(f"Failed ({response.status_code}): {response.text[:200]}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection error: Service may not be running - {str(e)[:100]}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        with entry_tab2:
            st.subheader("Card Entry (RFID/NFC/Magnetic)")
            st.markdown("**NEW in Phase 1.3**")
            
            if not st.session_state.store_id:
                st.warning("Please create a store first using the sidebar.")
            else:
                col1, col2 = st.columns(2)
                
                with col1:
                    card_number = st.text_input("Card Number", value="1234567890")
                    card_type = st.selectbox("Card Type", ["rfid", "nfc", "magnetic"])
                
                with col2:
                    device_id = st.text_input("Device ID", value="entry-device-01")
                
                if st.button("Create Card Entry"):
                    with st.spinner("Processing card entry..."):
                        try:
                            response = requests.post(
                                f"{CV_CONNECTOR_URL}/cv/entry/card",
                                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                json={
                                    "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                    "user_id": user_id,
                                    "store_id": st.session_state.store_id,
                                    "card_number": card_number,
                                    "card_type": card_type,
                                    "device_id": device_id
                                },
                                timeout=10
                            )
                            
                            if response.status_code == 200:
                                result = response.json()
                                st.success("Card entry created successfully!")
                                st.json(result)
                            else:
                                st.error(f"Failed ({response.status_code}): {response.text[:200]}")
                        except requests.exceptions.RequestException as e:
                            st.error(f"Connection error: {str(e)[:100]}")
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
        
        with entry_tab3:
            st.subheader("Biometric Entry (Face/Fingerprint/Palm/Iris)")
            st.markdown("**NEW in Phase 1.3**")
            
            if not st.session_state.store_id:
                st.warning("Please create a store first using the sidebar.")
            else:
                col1, col2 = st.columns(2)
                
                with col1:
                    biometric_type = st.selectbox("Biometric Type", ["face", "fingerprint", "palm", "iris"])
                    confidence_score = st.slider("Confidence Score", 0.0, 1.0, 0.95, 0.01, help="Minimum: 0.85")
                
                with col2:
                    biometric_data = st.text_input("Biometric Data (hash)", value="base64_encoded_hash")
                    bio_device_id = st.text_input("Device ID", value="biometric-scanner-01", key="bio_device")
                
                if st.button("Create Biometric Entry"):
                    if confidence_score < 0.85:
                        st.error("Confidence score must be >= 0.85 (85%)")
                    else:
                        with st.spinner("Processing biometric entry..."):
                            try:
                                response = requests.post(
                                    f"{CV_CONNECTOR_URL}/cv/entry/biometric",
                                    headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                    json={
                                        "tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa",
                                        "user_id": user_id,
                                        "store_id": st.session_state.store_id,
                                        "biometric_type": biometric_type,
                                        "biometric_data": biometric_data,
                                        "confidence_score": confidence_score,
                                        "device_id": bio_device_id
                                    },
                                    timeout=10
                                )
                                
                                if response.status_code == 200:
                                    result = response.json()
                                    st.success(f"Biometric entry created! Type: {result.get('biometric_type', 'N/A')}, Confidence: {result.get('confidence_score', 'N/A')}")
                                    st.json(result)
                                else:
                                    st.error(f"Failed ({response.status_code}): {response.text[:200]}")
                            except requests.exceptions.RequestException as e:
                                st.error(f"Connection error: {str(e)[:100]}")
                            except Exception as e:
                                st.error(f"Error: {str(e)}")

# ============================================
# TAB 4: SITE & DEVICE REGISTRY
# ============================================
with tab4:
    st.header("Site Registry with Device Metadata")
    st.markdown("**Phase 2.1**: Create sites with cameras, sensors, and entry devices")
    
    if not st.session_state.tenant_id:
        st.warning("Please create a tenant first using the sidebar.")
    else:
        st.markdown(f"**Current Tenant**: `{st.session_state.tenant_id[:16]}...`")
        
        st.subheader("Create Site with Devices")
        
        col1, col2 = st.columns(2)
        
        with col1:
            site_name = st.text_input("Site Name", value=f"Store_{datetime.now().strftime('%H%M%S')}")
            site_type = st.selectbox("Site Type", ["retail", "office", "warehouse"])
            
            st.markdown("**Location**")
            lat = st.number_input("Latitude", value=40.7128, format="%.6f")
            lon = st.number_input("Longitude", value=-74.0060, format="%.6f")
        
        with col2:
            st.markdown("**Devices**")
            num_cameras = st.number_input("Cameras", min_value=0, max_value=20, value=2)
            num_sensors = st.number_input("Sensors", min_value=0, max_value=20, value=1)
            num_entry_devices = st.number_input("Entry Devices", min_value=0, max_value=10, value=1)
        
        # Build device metadata
        cameras = [{"id": f"cam-{i+1:02d}", "type": "overhead" if i==0 else "entrance", "zone": "checkout" if i==0 else "entry"} for i in range(num_cameras)]
        sensors = [{"id": f"sensor-{i+1:02d}", "type": "motion", "zone": "entry"} for i in range(num_sensors)]
        entry_devices = [{"id": f"entry-{i+1:02d}", "type": "rfid_reader"} for i in range(num_entry_devices)]
        
        device_metadata = {"cameras": cameras, "sensors": sensors, "entry_devices": entry_devices}
        
        st.markdown("**Device Metadata Preview:**")
        st.json(device_metadata)
        
        if st.button("Create Site with Devices", type="primary"):
            site_id = str(uuid.uuid4())
            with st.spinner("Creating site..."):
                try:
                    response = requests.put(
                        f"{PROVISIONING_URL}/provisioning/sites/{site_id}",
                        headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                        params={"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa"},
                        json={
                            "name": site_name,
                            "site_type": site_type,
                            "geo": {"lat": lat, "lon": lon},
                            "device_metadata": device_metadata
                        }
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        st.session_state.site_id = site_id
                        st.success(f"Site created successfully! ID: {site_id[:16]}...")
                        st.info(f"SITE_CREATED event published. CV Gateway will sync {num_cameras + num_sensors + num_entry_devices} devices.")
                        st.json(result)
                    else:
                        st.error(f"Failed: {response.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

# ============================================
# TAB 5: DEVICE MONITORING
# ============================================
with tab5:
    st.header("Device Monitoring")
    st.markdown("**Phase 2.2**: Real-time device health monitoring")
    
    if not st.session_state.tenant_id:
        st.warning("Please create a tenant and site with devices first.")
    else:
        st.markdown(f"**Current Tenant**: `{st.session_state.tenant_id[:16]}...`")
        
        device_tab1, device_tab2, device_tab3 = st.tabs(["List Devices", "Device Status", "Update Status"])
        
        with device_tab1:
            st.subheader("List All Devices")
            
            col1, col2 = st.columns(2)
            
            with col1:
                filter_site = st.text_input("Filter by Site ID (optional)", value=st.session_state.site_id or "")
            with col2:
                filter_status = st.selectbox("Filter by Status", ["All", "online", "offline", "error", "maintenance"])
            
            if st.button("Refresh Devices"):
                with st.spinner("Loading devices..."):
                    try:
                        params = {"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa"}
                        if filter_site:
                            params["site_id"] = filter_site
                        if filter_status != "All":
                            params["status"] = filter_status
                        
                        response = requests.get(
                            f"{CV_GATEWAY_URL}/devices/status",
                            headers={"x-api-key": API_KEY},
                            params=params,
                            timeout=10
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            devices = result.get("devices", [])
                            
                            st.success(f"Found {result['total_devices']} device(s)")
                            
                            if devices:
                                for device in devices:
                                    status_indicator = {
                                        "online": "[OK]",
                                        "offline": "[OFFLINE]",
                                        "error": "[ERROR]",
                                        "maintenance": "[MAINT]"
                                    }.get(device['status'], "[?]")
                                    
                                    with st.expander(f"{status_indicator} {device['device_name']} ({device['device_type']})"):
                                        col_a, col_b, col_c = st.columns(3)
                                        with col_a:
                                            st.metric("Status", device['status'])
                                        with col_b:
                                            st.metric("Health", device.get('health_score', 'N/A'))
                                        with col_c:
                                            st.metric("Zone", device.get('zone', 'N/A'))
                                        st.json(device)
                            else:
                                st.info("No devices found. Create a site with devices in the Site Registry tab, then wait 5-10 seconds for event processing.")
                        else:
                            st.error(f"Failed ({response.status_code}): {response.text[:200]}")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Connection error: {str(e)[:100]}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        
        with device_tab2:
            st.subheader("Get Device Status")
            
            device_id = st.text_input("Device ID", placeholder="e.g., cam-01, sensor-01")
            
            if st.button("Get Status"):
                if not device_id:
                    st.warning("Please enter a Device ID")
                else:
                    with st.spinner("Loading device status..."):
                        try:
                            response = requests.get(
                                f"{CV_GATEWAY_URL}/devices/{device_id}/status",
                                headers={"x-api-key": API_KEY},
                                params={"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa"},
                                timeout=10
                            )
                            
                            if response.status_code == 200:
                                result = response.json()
                                st.success(f"Device: {result['device_name']}")
                                
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("Status", result['status'])
                                with col2:
                                    st.metric("Health", result.get('health_score', 'N/A'))
                                with col3:
                                    st.metric("Type", result['device_type'])
                                with col4:
                                    st.metric("Zone", result.get('zone', 'N/A'))
                                
                                st.markdown("**Recent Logs:**")
                                if result.get('recent_logs'):
                                    for log in result['recent_logs'][:5]:
                                        st.text(f"{log['created_at']}: {log['status']} (health: {log.get('health_score', 'N/A')})")
                                
                                st.markdown("**Open Alerts:**")
                                if result.get('open_alerts'):
                                    for alert in result['open_alerts']:
                                        st.warning(f"[{alert['severity'].upper()}] {alert['message']}")
                                else:
                                    st.success("No open alerts")
                            else:
                                st.error(f"Failed ({response.status_code}): {response.text[:200]}")
                        except requests.exceptions.RequestException as e:
                            st.error(f"Connection error: {str(e)[:100]}")
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
        
        with device_tab3:
            st.subheader("Update Device Status")
            
            update_device_id = st.text_input("Device ID", placeholder="e.g., cam-01", key="update_dev")
            
            col1, col2 = st.columns(2)
            
            with col1:
                new_status = st.selectbox("New Status", ["online", "offline", "error", "maintenance"])
                new_health_score = st.slider("Health Score", 0, 100, 95)
            
            with col2:
                details_json = st.text_area(
                    "Details (JSON)",
                    value='{"temperature": 22.5, "uptime_hours": 168}',
                    height=100
                )
            
            if st.button("Update Device Status"):
                if not update_device_id:
                    st.warning("Please enter a Device ID")
                else:
                    with st.spinner("Updating device status..."):
                        try:
                            details = json.loads(details_json) if details_json else {}
                            
                            response = requests.put(
                                f"{CV_GATEWAY_URL}/devices/{update_device_id}/status",
                                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                                params={"tenant_id": str(st.session_state.tenant_id) if st.session_state.tenant_id else "733bc6e1-458b-4922-b2de-8213201dd3fa"},
                                json={
                                    "status": new_status,
                                    "health_score": new_health_score,
                                    "details": details
                                },
                                timeout=10
                            )
                            
                            if response.status_code == 200:
                                result = response.json()
                                st.success(f"Status updated: {result.get('old_status', '?')} → {result['new_status']}")
                                if new_status in ["offline", "error"]:
                                    st.info("Alert automatically created for status change")
                                st.json(result)
                            else:
                                st.error(f"Failed ({response.status_code}): {response.text[:200]}")
                        except json.JSONDecodeError:
                            st.error("Invalid JSON in details field")
                        except requests.exceptions.RequestException as e:
                            st.error(f"Connection error: {str(e)[:100]}")
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

# Footer
st.markdown("---")
st.markdown("""
**ZeroQue V4.1 - Phase 1 & 2 Features**  
Documentation: `/docs/PHASE_1_2_API_DOCUMENTATION.md`  
Tests: `/tests/test_phase1_phase2.sh`  
Migration: `/alembic/versions/add_phase1_phase2_features.py`
""")

# Service status
st.sidebar.markdown("---")
st.sidebar.subheader("Service Status")

services = {
    "Provisioning": (PROVISIONING_URL, 8000),
    "Identity": (IDENTITY_URL, 8003),
    "CV Connector": (CV_CONNECTOR_URL, 8216),
    "CV Gateway": (CV_GATEWAY_URL, 8215),
    "Entry": (ENTRY_URL, 8200)
}

for service_name, (url, port) in services.items():
    try:
        response = requests.get(f"{url}/health", timeout=2)
        if response.status_code == 200:
            st.sidebar.success(f"[OK] {service_name}")
        else:
            st.sidebar.warning(f"[WARN] {service_name}")
    except:
        st.sidebar.error(f"[OFFLINE] {service_name}")
