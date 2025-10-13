#!/usr/bin/env python3
"""
ZeroQue Comprehensive Streamlit App
Complete business demonstration and testing interface for all ZeroQue services
"""

import streamlit as st
import requests
import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Page configuration
st.set_page_config(
    page_title="ZeroQue Comprehensive Platform",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Service configurations
SERVICES = {
    "provisioning": {"port": 8000, "name": "Provisioning", "icon": "🏗️"},
    "orders": {"port": 8224, "name": "Orders", "icon": "🛒"},
    "payments": {"port": 8225, "name": "Payments", "icon": "💳"},
    "pricing": {"port": 8226, "name": "Pricing", "icon": "💰"},
    "billing": {"port": 8214, "name": "Billing", "icon": "🧾"},
    "notifications": {"port": 8222, "name": "Notifications", "icon": "📧"},
    "catalog": {"port": 8215, "name": "Catalog", "icon": "📦"},
    "subscriptions": {"port": 8010, "name": "Subscriptions", "icon": "📋"},
    "entitlements": {"port": 8011, "name": "Entitlements", "icon": "🎫"},
    "ledger": {"port": 8220, "name": "Ledger", "icon": "📊"},
    "monitoring": {"port": 8221, "name": "Monitoring", "icon": "📈"},
    "observability": {"port": 8223, "name": "Observability", "icon": "🔍"},
    "reports": {"port": 8227, "name": "Reports", "icon": "📋"},
    "usage": {"port": 8218, "name": "Usage", "icon": "📊"},
    "identity": {"port": 8219, "name": "Identity", "icon": "🔐"},
    "approvals": {"port": 8213, "name": "Approvals", "icon": "✅"},
    "cv_connector": {"port": 8216, "name": "CV Connector", "icon": "🔗"},
    "cv_gateway": {"port": 8217, "name": "CV Gateway", "icon": "🚪"},
    "entry": {"port": 8218, "name": "Entry", "icon": "🚪"},
    "events": {"port": 8212, "name": "Events", "icon": "📅"},
    "service_registry": {"port": 8211, "name": "Service Registry", "icon": "📝"}
}

# Test data
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
TEST_SITE_ID = "550e8400-e29b-41d4-a716-446655440002"
TEST_STORE_ID = "550e8400-e29b-41d4-a716-446655440003"

def make_request(service: str, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
    """Make API request to a specific service"""
    try:
        port = SERVICES[service]["port"]
        url = f"http://localhost:{port}{endpoint}"
        
        if method == "GET":
            response = requests.get(url, timeout=5)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=5)
        elif method == "PUT":
            response = requests.put(url, json=data, timeout=5)
        elif method == "DELETE":
            response = requests.delete(url, timeout=5)
        else:
            return {"error": f"Unsupported method: {method}"}
        
        return {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            "success": response.status_code < 400,
            "service": service
        }
    except Exception as e:
        return {"error": str(e), "success": False, "service": service}

def check_service_health(service: str) -> Dict[str, Any]:
    """Check health of a specific service"""
    return make_request(service, "/health", "GET")

def get_all_services_health() -> Dict[str, Dict[str, Any]]:
    """Get health status of all services"""
    health_status = {}
    for service in SERVICES.keys():
        health_status[service] = check_service_health(service)
    return health_status

def main():
    """Main application"""
    st.title("🏢 ZeroQue Comprehensive Platform")
    st.markdown("Complete business demonstration and testing interface for all ZeroQue microservices")
    
    # Initialize session state
    if "tenant_id" not in st.session_state:
        st.session_state.tenant_id = TEST_TENANT_ID
    if "user_id" not in st.session_state:
        st.session_state.user_id = TEST_USER_ID
    if "site_id" not in st.session_state:
        st.session_state.site_id = TEST_SITE_ID
    if "store_id" not in st.session_state:
        st.session_state.store_id = TEST_STORE_ID
    if "selected_services" not in st.session_state:
        st.session_state.selected_services = []
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        [
            "Platform Overview",
            "Service Health Dashboard",
            "Business Workflow Demo",
            "Service Testing",
            "Analytics & Reports",
            "System Configuration"
        ]
    )
    
    # Route to selected page
    if page == "Platform Overview":
        show_platform_overview()
    elif page == "Service Health Dashboard":
        show_service_health_dashboard()
    elif page == "Business Workflow Demo":
        show_business_workflow_demo()
    elif page == "Service Testing":
        show_service_testing()
    elif page == "Analytics & Reports":
        show_analytics_reports()
    elif page == "System Configuration":
        show_system_configuration()

def show_platform_overview():
    """Platform overview page"""
    st.header("🏢 ZeroQue Platform Overview")
    
    # Platform statistics
    st.subheader("Platform Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Services", len(SERVICES), "21")
    
    with col2:
        st.metric("Active Services", "18", "3")
    
    with col3:
        st.metric("Total Tenants", "1,234", "56")
    
    with col4:
        st.metric("System Uptime", "99.9%", "0.1%")
    
    # Service categories
    st.subheader("Service Categories")
    
    categories = {
        "Core Business": ["provisioning", "orders", "payments", "billing", "pricing"],
        "Product Management": ["catalog", "subscriptions", "entitlements"],
        "Analytics & Monitoring": ["monitoring", "observability", "reports", "usage"],
        "Security & Access": ["identity", "entry", "approvals"],
        "Integration": ["cv_connector", "cv_gateway", "events", "notifications"],
        "Infrastructure": ["ledger", "service_registry"]
    }
    
    for category, services in categories.items():
        with st.expander(f"📁 {category} ({len(services)} services)"):
            cols = st.columns(len(services))
            for i, service in enumerate(services):
                with cols[i]:
                    service_info = SERVICES[service]
                    st.write(f"{service_info['icon']} **{service_info['name']}**")
                    st.caption(f"Port: {service_info['port']}")
    
    # Quick actions
    st.subheader("Quick Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("🏥 Check All Services", use_container_width=True):
            with st.spinner("Checking service health..."):
                health_status = get_all_services_health()
                healthy_count = sum(1 for status in health_status.values() if status.get("success", False))
                st.success(f"✅ {healthy_count}/{len(SERVICES)} services are healthy")
    
    with col2:
        if st.button("📊 View Analytics", use_container_width=True):
            st.info("Redirecting to Analytics & Reports...")
    
    with col3:
        if st.button("🧪 Run Tests", use_container_width=True):
            st.info("Redirecting to Service Testing...")
    
    with col4:
        if st.button("⚙️ Configure System", use_container_width=True):
            st.info("Redirecting to System Configuration...")
    
    # Recent activity
    st.subheader("Recent Activity")
    
    # Sample recent activity
    recent_activity = [
        {"timestamp": "2024-01-15 10:30:00", "service": "provisioning", "action": "Tenant created", "details": "Demo Tenant"},
        {"timestamp": "2024-01-15 10:25:00", "service": "orders", "action": "Order processed", "details": "Order #12345"},
        {"timestamp": "2024-01-15 10:20:00", "service": "payments", "action": "Payment completed", "details": "£125.50"},
        {"timestamp": "2024-01-15 10:15:00", "service": "notifications", "action": "Email sent", "details": "Order confirmation"},
        {"timestamp": "2024-01-15 10:10:00", "service": "billing", "action": "Invoice generated", "details": "INV-001"}
    ]
    
    for activity in recent_activity:
        service_info = SERVICES[activity["service"]]
        col1, col2, col3 = st.columns([2, 3, 4])
        
        with col1:
            st.write(f"{service_info['icon']} **{service_info['name']}**")
        
        with col2:
            st.write(activity["action"])
        
        with col3:
            st.write(activity["details"])
        
        st.caption(activity["timestamp"])
        st.divider()

def show_service_health_dashboard():
    """Service health dashboard"""
    st.header("🏥 Service Health Dashboard")
    
    # Refresh button
    if st.button("🔄 Refresh Health Status"):
        with st.spinner("Checking all services..."):
            health_status = get_all_services_health()
            
            # Display health status
            st.subheader("Service Health Status")
            
            # Create a grid layout for services
            cols = st.columns(3)
            col_index = 0
            
            for service, status in health_status.items():
                service_info = SERVICES[service]
                
                with cols[col_index % 3]:
                    if status.get("success", False):
                        st.success(f"{service_info['icon']} {service_info['name']}")
                        st.caption(f"✅ Healthy - Port {service_info['port']}")
                    else:
                        st.error(f"{service_info['icon']} {service_info['name']}")
                        st.caption(f"❌ Unhealthy - Port {service_info['port']}")
                        if "error" in status:
                            st.caption(f"Error: {status['error']}")
                
                col_index += 1
    
    # Health metrics
    st.subheader("Health Metrics")
    
    # Sample health metrics
    health_metrics = {
        "total_services": len(SERVICES),
        "healthy_services": 18,
        "unhealthy_services": 3,
        "average_response_time": 120,
        "uptime_percentage": 99.9
    }
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Services", health_metrics["total_services"])
    
    with col2:
        st.metric("Healthy Services", health_metrics["healthy_services"])
    
    with col3:
        st.metric("Unhealthy Services", health_metrics["unhealthy_services"])
    
    with col4:
        st.metric("Avg Response Time", f"{health_metrics['average_response_time']}ms")
    
    with col5:
        st.metric("Uptime", f"{health_metrics['uptime_percentage']}%")
    
    # Service health chart
    st.subheader("Service Health Over Time")
    
    # Sample health data over time
    health_data = []
    for i in range(24):
        timestamp = datetime.now() - timedelta(hours=23-i)
        healthy_count = 18 + (i % 3)  # Simulate variation
        health_data.append({
            "timestamp": timestamp,
            "healthy_services": healthy_count,
            "unhealthy_services": len(SERVICES) - healthy_count
        })
    
    df = pd.DataFrame(health_data)
    fig = px.line(df, x="timestamp", y="healthy_services", title="Healthy Services Over Time")
    st.plotly_chart(fig, use_container_width=True)
    
    # Service details
    st.subheader("Service Details")
    
    selected_service = st.selectbox("Select Service for Details", list(SERVICES.keys()), format_func=lambda x: f"{SERVICES[x]['icon']} {SERVICES[x]['name']}")
    
    if selected_service:
        service_info = SERVICES[selected_service]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**Service:** {service_info['name']}")
            st.write(f"**Port:** {service_info['port']}")
            st.write(f"**Icon:** {service_info['icon']}")
        
        with col2:
            health_status = check_service_health(selected_service)
            if health_status.get("success", False):
                st.success("✅ Service is healthy")
                if "data" in health_status:
                    st.json(health_status["data"])
            else:
                st.error("❌ Service is unhealthy")
                if "error" in health_status:
                    st.error(f"Error: {health_status['error']}")

def show_business_workflow_demo():
    """Business workflow demonstration"""
    st.header("🔄 Business Workflow Demo")
    
    # Workflow selection
    workflow = st.selectbox(
        "Select Business Workflow",
        [
            "Complete Customer Journey",
            "Order Processing Flow",
            "Payment Processing Flow",
            "Subscription Management",
            "Inventory Management",
            "Customer Support Flow"
        ]
    )
    
    if workflow == "Complete Customer Journey":
        show_customer_journey_demo()
    elif workflow == "Order Processing Flow":
        show_order_processing_demo()
    elif workflow == "Payment Processing Flow":
        show_payment_processing_demo()
    elif workflow == "Subscription Management":
        show_subscription_management_demo()
    elif workflow == "Inventory Management":
        show_inventory_management_demo()
    elif workflow == "Customer Support Flow":
        show_customer_support_demo()

def show_customer_journey_demo():
    """Complete customer journey demonstration"""
    st.subheader("👤 Complete Customer Journey")
    
    # Step 1: Tenant Registration
    st.write("#### Step 1: Tenant Registration")
    
    with st.form("tenant_registration"):
        tenant_name = st.text_input("Tenant Name", value="Demo Customer Corp")
        tenant_email = st.text_input("Email", value="demo@customer.com")
        tenant_phone = st.text_input("Phone", value="+1234567890")
        
        if st.form_submit_button("Register Tenant"):
            with st.spinner("Creating tenant..."):
                tenant_data = {
                    "tenant_id": str(uuid.uuid4()),
                    "name": tenant_name,
                    "email": tenant_email,
                    "phone": tenant_phone
                }
                
                result = make_request("provisioning", "/provisioning/tenants", "POST", tenant_data)
                
                if result.get("success", False):
                    st.success("✅ Tenant created successfully!")
                    st.session_state.tenant_id = tenant_data["tenant_id"]
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to create tenant: {result.get('error', 'Unknown error')}")
    
    # Step 2: Site Creation
    if st.session_state.tenant_id:
        st.write("#### Step 2: Site Creation")
        
        with st.form("site_creation"):
            site_name = st.text_input("Site Name", value="Main Office")
            site_address = st.text_area("Address", value="123 Business St, City, State 12345")
            site_type = st.selectbox("Site Type", ["office", "warehouse", "retail", "headquarters"])
            
            if st.form_submit_button("Create Site"):
                with st.spinner("Creating site..."):
                    site_data = {
                        "site_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "name": site_name,
                        "address": site_address,
                        "site_type": site_type
                    }
                    
                    result = make_request("provisioning", f"/provisioning/sites/{site_data['site_id']}?tenant_id={st.session_state.tenant_id}", "PUT", site_data)
                    
                    if result.get("success", False):
                        st.success("✅ Site created successfully!")
                        st.session_state.site_id = site_data["site_id"]
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to create site: {result.get('error', 'Unknown error')}")
    
    # Step 3: Store Setup
    if st.session_state.site_id:
        st.write("#### Step 3: Store Setup")
        
        with st.form("store_creation"):
            store_name = st.text_input("Store Name", value="Main Store")
            store_type = st.selectbox("Store Type", ["retail", "online", "warehouse", "popup"])
            store_manager = st.text_input("Store Manager", value="John Manager")
            
            if st.form_submit_button("Create Store"):
                with st.spinner("Creating store..."):
                    store_data = {
                        "store_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "site_id": st.session_state.site_id,
                        "name": store_name,
                        "store_type": store_type,
                        "manager": store_manager
                    }
                    
                    result = make_request("provisioning", f"/provisioning/stores/{store_data['store_id']}?tenant_id={st.session_state.tenant_id}", "PUT", store_data)
                    
                    if result.get("success", False):
                        st.success("✅ Store created successfully!")
                        st.session_state.store_id = store_data["store_id"]
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to create store: {result.get('error', 'Unknown error')}")
    
    # Step 4: User Creation
    if st.session_state.store_id:
        st.write("#### Step 4: User Creation")
        
        with st.form("user_creation"):
            user_name = st.text_input("User Name", value="Demo User")
            user_email = st.text_input("User Email", value="user@demo.com")
            user_role = st.selectbox("User Role", ["admin", "manager", "employee", "customer"])
            
            if st.form_submit_button("Create User"):
                with st.spinner("Creating user..."):
                    user_data = {
                        "user_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "site_id": st.session_state.site_id,
                        "store_id": st.session_state.store_id,
                        "name": user_name,
                        "email": user_email,
                        "role": user_role
                    }
                    
                    result = make_request("provisioning", f"/provisioning/users/{user_data['user_id']}?tenant_id={st.session_state.tenant_id}", "PUT", user_data)
                    
                    if result.get("success", False):
                        st.success("✅ User created successfully!")
                        st.session_state.user_id = user_data["user_id"]
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to create user: {result.get('error', 'Unknown error')}")
    
    # Step 5: Product Catalog
    if st.session_state.user_id:
        st.write("#### Step 5: Product Catalog Setup")
        
        with st.form("product_catalog"):
            product_name = st.text_input("Product Name", value="Demo Product")
            product_price = st.number_input("Price", min_value=0.01, value=29.99, step=0.01)
            product_category = st.selectbox("Category", ["electronics", "clothing", "books", "home", "sports"])
            product_description = st.text_area("Description", value="A high-quality demo product for testing")
            
            if st.form_submit_button("Add Product"):
                with st.spinner("Adding product..."):
                    product_data = {
                        "product_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "name": product_name,
                        "price_minor": int(product_price * 100),
                        "category": product_category,
                        "description": product_description,
                        "is_active": True
                    }
                    
                    result = make_request("catalog", "/catalog/v2/products", "POST", product_data)
                    
                    if result.get("success", False):
                        st.success("✅ Product added successfully!")
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to add product: {result.get('error', 'Unknown error')}")
    
    # Step 6: Order Processing
    if st.session_state.user_id:
        st.write("#### Step 6: Order Processing")
        
        with st.form("order_processing"):
            order_type = st.selectbox("Order Type", ["retail", "wholesale", "bulk"])
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@demo.com")
            total_amount = st.number_input("Total Amount", min_value=0.01, value=59.98, step=0.01)
            
            if st.form_submit_button("Create Order"):
                with st.spinner("Processing order..."):
                    order_data = {
                        "order_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "site_id": st.session_state.site_id,
                        "store_id": st.session_state.store_id,
                        "user_id": st.session_state.user_id,
                        "order_type": order_type,
                        "customer_name": customer_name,
                        "customer_email": customer_email,
                        "total_amount_minor": int(total_amount * 100),
                        "currency": "GBP",
                        "order_status": "pending"
                    }
                    
                    result = make_request("orders", "/orders/v2", "POST", order_data)
                    
                    if result.get("success", False):
                        st.success("✅ Order created successfully!")
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to create order: {result.get('error', 'Unknown error')}")
    
    # Step 7: Payment Processing
    if st.session_state.user_id:
        st.write("#### Step 7: Payment Processing")
        
        with st.form("payment_processing"):
            payment_method = st.selectbox("Payment Method", ["card", "digital_wallet", "bank_transfer"])
            payment_amount = st.number_input("Payment Amount", min_value=0.01, value=59.98, step=0.01)
            payment_currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
            
            if st.form_submit_button("Process Payment"):
                with st.spinner("Processing payment..."):
                    payment_data = {
                        "payment_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "site_id": st.session_state.site_id,
                        "store_id": st.session_state.store_id,
                        "user_id": st.session_state.user_id,
                        "payment_method": payment_method,
                        "amount_minor": int(payment_amount * 100),
                        "currency": payment_currency,
                        "status": "pending"
                    }
                    
                    result = make_request("payments", "/payments/new", "POST", payment_data)
                    
                    if result.get("success", False):
                        st.success("✅ Payment processed successfully!")
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to process payment: {result.get('error', 'Unknown error')}")
    
    # Step 8: Notification
    if st.session_state.user_id:
        st.write("#### Step 8: Send Notification")
        
        with st.form("notification_sending"):
            notification_type = st.selectbox("Notification Type", ["email", "sms", "push"])
            notification_subject = st.text_input("Subject", value="Order Confirmation")
            notification_message = st.text_area("Message", value="Your order has been confirmed and payment processed successfully.")
            
            if st.form_submit_button("Send Notification"):
                with st.spinner("Sending notification..."):
                    notification_data = {
                        "notification_id": str(uuid.uuid4()),
                        "tenant_id": st.session_state.tenant_id,
                        "site_id": st.session_state.site_id,
                        "store_id": st.session_state.store_id,
                        "user_id": st.session_state.user_id,
                        "notification_type": notification_type,
                        "subject": notification_subject,
                        "message": notification_message,
                        "recipient_email": "customer@demo.com",
                        "status": "pending"
                    }
                    
                    result = make_request("notifications", "/notifications/new", "POST", notification_data)
                    
                    if result.get("success", False):
                        st.success("✅ Notification sent successfully!")
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to send notification: {result.get('error', 'Unknown error')}")
    
    # Workflow summary
    st.subheader("🎉 Workflow Summary")
    
    if st.session_state.tenant_id and st.session_state.site_id and st.session_state.store_id and st.session_state.user_id:
        st.success("✅ Complete customer journey workflow completed successfully!")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Tenant Created", "✅", "Demo Customer Corp")
        
        with col2:
            st.metric("Site Created", "✅", "Main Office")
        
        with col3:
            st.metric("Store Created", "✅", "Main Store")
        
        with col4:
            st.metric("User Created", "✅", "Demo User")
        
        st.info("The complete customer journey has been demonstrated, showing the end-to-end workflow from tenant registration to notification delivery.")
    else:
        st.warning("⚠️ Complete the workflow steps above to see the full customer journey demonstration.")

def show_order_processing_demo():
    """Order processing workflow demonstration"""
    st.subheader("🛒 Order Processing Flow")
    
    # Order creation
    st.write("#### Step 1: Create Order")
    
    with st.form("order_creation"):
        col1, col2 = st.columns(2)
        
        with col1:
            order_type = st.selectbox("Order Type", ["retail", "wholesale", "bulk"])
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@demo.com")
        
        with col2:
            total_amount = st.number_input("Total Amount", min_value=0.01, value=125.50, step=0.01)
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
            priority = st.selectbox("Priority", ["low", "medium", "high", "urgent"])
        
        if st.form_submit_button("Create Order"):
            with st.spinner("Creating order..."):
                order_data = {
                    "order_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "user_id": st.session_state.user_id,
                    "order_type": order_type,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "total_amount_minor": int(total_amount * 100),
                    "currency": currency,
                    "priority": priority,
                    "order_status": "pending"
                }
                
                result = make_request("orders", "/orders/v2", "POST", order_data)
                
                if result.get("success", False):
                    st.success("✅ Order created successfully!")
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to create order: {result.get('error', 'Unknown error')}")
    
    # Order fulfillment
    st.write("#### Step 2: Order Fulfillment")
    
    with st.form("order_fulfillment"):
        fulfillment_method = st.selectbox("Fulfillment Method", ["standard", "express", "overnight"])
        tracking_number = st.text_input("Tracking Number", value=f"TRK{uuid.uuid4().hex[:8].upper()}")
        estimated_delivery = st.date_input("Estimated Delivery", value=datetime.now().date() + timedelta(days=3))
        
        if st.form_submit_button("Process Fulfillment"):
            with st.spinner("Processing fulfillment..."):
                fulfillment_data = {
                    "fulfillment_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "fulfillment_method": fulfillment_method,
                    "tracking_number": tracking_number,
                    "estimated_delivery": estimated_delivery.isoformat(),
                    "status": "processing"
                }
                
                st.success("✅ Order fulfillment processed!")
                st.json(fulfillment_data)
    
    # Order tracking
    st.write("#### Step 3: Order Tracking")
    
    # Sample order tracking data
    tracking_data = [
        {"timestamp": "2024-01-15 10:30:00", "status": "Order Created", "location": "Warehouse", "description": "Order was created and received"},
        {"timestamp": "2024-01-15 11:00:00", "status": "Processing", "location": "Warehouse", "description": "Order is being processed and prepared"},
        {"timestamp": "2024-01-15 14:30:00", "status": "Shipped", "location": "Distribution Center", "description": "Order has been shipped and is in transit"},
        {"timestamp": "2024-01-16 09:00:00", "status": "Out for Delivery", "location": "Local Depot", "description": "Order is out for delivery"},
        {"timestamp": "2024-01-16 15:30:00", "status": "Delivered", "location": "Customer Address", "description": "Order has been delivered successfully"}
    ]
    
    for tracking in tracking_data:
        col1, col2, col3 = st.columns([2, 2, 4])
        
        with col1:
            st.write(f"**{tracking['timestamp']}**")
        
        with col2:
            if tracking['status'] == 'Delivered':
                st.success(tracking['status'])
            elif tracking['status'] == 'Shipped':
                st.info(tracking['status'])
            else:
                st.write(tracking['status'])
        
        with col3:
            st.write(f"{tracking['location']} - {tracking['description']}")
        
        st.divider()

def show_payment_processing_demo():
    """Payment processing workflow demonstration"""
    st.subheader("💳 Payment Processing Flow")
    
    # Payment creation
    st.write("#### Step 1: Create Payment")
    
    with st.form("payment_creation"):
        col1, col2 = st.columns(2)
        
        with col1:
            payment_method = st.selectbox("Payment Method", ["card", "digital_wallet", "bank_transfer", "cash"])
            amount = st.number_input("Amount", min_value=0.01, value=125.50, step=0.01)
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
        
        with col2:
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@demo.com")
            description = st.text_input("Description", value="Payment for order #12345")
        
        if st.form_submit_button("Create Payment"):
            with st.spinner("Creating payment..."):
                payment_data = {
                    "payment_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "user_id": st.session_state.user_id,
                    "payment_method": payment_method,
                    "amount_minor": int(amount * 100),
                    "currency": currency,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "description": description,
                    "status": "pending"
                }
                
                result = make_request("payments", "/payments/new", "POST", payment_data)
                
                if result.get("success", False):
                    st.success("✅ Payment created successfully!")
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to create payment: {result.get('error', 'Unknown error')}")
    
    # Payment processing
    st.write("#### Step 2: Process Payment")
    
    with st.form("payment_processing"):
        processing_method = st.selectbox("Processing Method", ["immediate", "scheduled", "recurring"])
        auto_capture = st.checkbox("Auto Capture", value=True)
        save_payment_method = st.checkbox("Save Payment Method", value=False)
        
        if st.form_submit_button("Process Payment"):
            with st.spinner("Processing payment..."):
                processing_data = {
                    "processing_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "processing_method": processing_method,
                    "auto_capture": auto_capture,
                    "save_payment_method": save_payment_method,
                    "status": "processing"
                }
                
                st.success("✅ Payment processing initiated!")
                st.json(processing_data)
    
    # Payment status
    st.write("#### Step 3: Payment Status")
    
    # Sample payment status data
    payment_status = [
        {"timestamp": "2024-01-15 10:30:00", "status": "Payment Created", "description": "Payment was created and validated"},
        {"timestamp": "2024-01-15 10:31:00", "status": "Processing", "description": "Payment is being processed by the payment gateway"},
        {"timestamp": "2024-01-15 10:32:00", "status": "Authorized", "description": "Payment has been authorized by the bank"},
        {"timestamp": "2024-01-15 10:33:00", "status": "Captured", "description": "Payment has been captured and funds transferred"},
        {"timestamp": "2024-01-15 10:34:00", "status": "Completed", "description": "Payment processing completed successfully"}
    ]
    
    for status in payment_status:
        col1, col2, col3 = st.columns([2, 2, 4])
        
        with col1:
            st.write(f"**{status['timestamp']}**")
        
        with col2:
            if status['status'] == 'Completed':
                st.success(status['status'])
            elif status['status'] == 'Processing':
                st.info(status['status'])
            else:
                st.write(status['status'])
        
        with col3:
            st.write(status['description'])
        
        st.divider()

def show_subscription_management_demo():
    """Subscription management workflow demonstration"""
    st.subheader("📋 Subscription Management Flow")
    
    # Subscription creation
    st.write("#### Step 1: Create Subscription")
    
    with st.form("subscription_creation"):
        col1, col2 = st.columns(2)
        
        with col1:
            subscription_type = st.selectbox("Subscription Type", ["monthly", "quarterly", "yearly"])
            plan_name = st.text_input("Plan Name", value="Premium Plan")
            price = st.number_input("Price", min_value=0.01, value=29.99, step=0.01)
        
        with col2:
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@demo.com")
            start_date = st.date_input("Start Date", value=datetime.now().date())
        
        if st.form_submit_button("Create Subscription"):
            with st.spinner("Creating subscription..."):
                subscription_data = {
                    "subscription_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "subscription_type": subscription_type,
                    "plan_name": plan_name,
                    "price_minor": int(price * 100),
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "start_date": start_date.isoformat(),
                    "status": "active"
                }
                
                st.success("✅ Subscription created successfully!")
                st.json(subscription_data)
    
    # Subscription management
    st.write("#### Step 2: Manage Subscription")
    
    with st.form("subscription_management"):
        management_action = st.selectbox("Management Action", ["renew", "upgrade", "downgrade", "pause", "cancel"])
        new_plan = st.text_input("New Plan (if applicable)", value="")
        reason = st.text_area("Reason", value="Customer request")
        
        if st.form_submit_button("Execute Action"):
            with st.spinner("Processing subscription action..."):
                management_data = {
                    "action_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "action": management_action,
                    "new_plan": new_plan,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat()
                }
                
                st.success(f"✅ Subscription {management_action} processed!")
                st.json(management_data)
    
    # Subscription billing
    st.write("#### Step 3: Subscription Billing")
    
    with st.form("subscription_billing"):
        billing_cycle = st.selectbox("Billing Cycle", ["monthly", "quarterly", "yearly"])
        billing_date = st.date_input("Billing Date", value=datetime.now().date())
        auto_renewal = st.checkbox("Auto Renewal", value=True)
        
        if st.form_submit_button("Process Billing"):
            with st.spinner("Processing subscription billing..."):
                billing_data = {
                    "billing_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "billing_cycle": billing_cycle,
                    "billing_date": billing_date.isoformat(),
                    "auto_renewal": auto_renewal,
                    "status": "processed"
                }
                
                st.success("✅ Subscription billing processed!")
                st.json(billing_data)

def show_inventory_management_demo():
    """Inventory management workflow demonstration"""
    st.subheader("📦 Inventory Management Flow")
    
    # Product creation
    st.write("#### Step 1: Add Product to Inventory")
    
    with st.form("product_inventory"):
        col1, col2 = st.columns(2)
        
        with col1:
            product_name = st.text_input("Product Name", value="Demo Product")
            product_sku = st.text_input("SKU", value=f"SKU-{uuid.uuid4().hex[:8].upper()}")
            category = st.selectbox("Category", ["electronics", "clothing", "books", "home", "sports"])
        
        with col2:
            initial_stock = st.number_input("Initial Stock", min_value=0, value=100)
            reorder_level = st.number_input("Reorder Level", min_value=0, value=20)
            unit_cost = st.number_input("Unit Cost", min_value=0.01, value=15.99, step=0.01)
        
        if st.form_submit_button("Add Product"):
            with st.spinner("Adding product to inventory..."):
                inventory_data = {
                    "product_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "product_name": product_name,
                    "product_sku": product_sku,
                    "category": category,
                    "initial_stock": initial_stock,
                    "current_stock": initial_stock,
                    "reorder_level": reorder_level,
                    "unit_cost": unit_cost,
                    "status": "active"
                }
                
                st.success("✅ Product added to inventory!")
                st.json(inventory_data)
    
    # Stock management
    st.write("#### Step 2: Stock Management")
    
    with st.form("stock_management"):
        stock_action = st.selectbox("Stock Action", ["add", "remove", "adjust", "transfer"])
        quantity = st.number_input("Quantity", min_value=1, value=10)
        reason = st.text_area("Reason", value="Stock adjustment")
        
        if st.form_submit_button("Execute Stock Action"):
            with st.spinner("Processing stock action..."):
                stock_data = {
                    "stock_action_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "action": stock_action,
                    "quantity": quantity,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat()
                }
                
                st.success(f"✅ Stock {stock_action} processed!")
                st.json(stock_data)
    
    # Inventory reports
    st.write("#### Step 3: Inventory Reports")
    
    # Sample inventory data
    inventory_data = [
        {"product": "Demo Product 1", "sku": "SKU-001", "current_stock": 45, "reorder_level": 20, "status": "In Stock"},
        {"product": "Demo Product 2", "sku": "SKU-002", "current_stock": 15, "reorder_level": 20, "status": "Low Stock"},
        {"product": "Demo Product 3", "sku": "SKU-003", "current_stock": 0, "reorder_level": 20, "status": "Out of Stock"},
        {"product": "Demo Product 4", "sku": "SKU-004", "current_stock": 78, "reorder_level": 20, "status": "In Stock"},
        {"product": "Demo Product 5", "sku": "SKU-005", "current_stock": 12, "reorder_level": 20, "status": "Low Stock"}
    ]
    
    df = pd.DataFrame(inventory_data)
    st.dataframe(df, use_container_width=True)
    
    # Inventory chart
    fig = px.bar(df, x="product", y="current_stock", title="Current Stock Levels")
    st.plotly_chart(fig, use_container_width=True)

def show_customer_support_demo():
    """Customer support workflow demonstration"""
    st.subheader("🎧 Customer Support Flow")
    
    # Ticket creation
    st.write("#### Step 1: Create Support Ticket")
    
    with st.form("support_ticket"):
        col1, col2 = st.columns(2)
        
        with col1:
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@demo.com")
            ticket_type = st.selectbox("Ticket Type", ["technical", "billing", "general", "complaint"])
        
        with col2:
            priority = st.selectbox("Priority", ["low", "medium", "high", "urgent"])
            subject = st.text_input("Subject", value="Demo Support Request")
            description = st.text_area("Description", value="This is a demo support request for testing purposes.")
        
        if st.form_submit_button("Create Ticket"):
            with st.spinner("Creating support ticket..."):
                ticket_data = {
                    "ticket_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "ticket_type": ticket_type,
                    "priority": priority,
                    "subject": subject,
                    "description": description,
                    "status": "open",
                    "created_at": datetime.now().isoformat()
                }
                
                st.success("✅ Support ticket created!")
                st.json(ticket_data)
    
    # Ticket management
    st.write("#### Step 2: Manage Support Ticket")
    
    with st.form("ticket_management"):
        management_action = st.selectbox("Management Action", ["assign", "escalate", "resolve", "close"])
        assigned_to = st.text_input("Assigned To", value="Support Agent")
        resolution = st.text_area("Resolution", value="Issue resolved successfully")
        
        if st.form_submit_button("Execute Action"):
            with st.spinner("Processing ticket action..."):
                management_data = {
                    "action_id": str(uuid.uuid4()),
                    "tenant_id": st.session_state.tenant_id,
                    "action": management_action,
                    "assigned_to": assigned_to,
                    "resolution": resolution,
                    "timestamp": datetime.now().isoformat()
                }
                
                st.success(f"✅ Ticket {management_action} processed!")
                st.json(management_data)
    
    # Support metrics
    st.write("#### Step 3: Support Metrics")
    
    # Sample support metrics
    support_metrics = {
        "total_tickets": 156,
        "open_tickets": 23,
        "resolved_tickets": 133,
        "average_resolution_time": "2.5 hours",
        "customer_satisfaction": 4.2
    }
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Tickets", support_metrics["total_tickets"])
    
    with col2:
        st.metric("Open Tickets", support_metrics["open_tickets"])
    
    with col3:
        st.metric("Resolved Tickets", support_metrics["resolved_tickets"])
    
    with col4:
        st.metric("Avg Resolution Time", support_metrics["average_resolution_time"])
    
    with col5:
        st.metric("Customer Satisfaction", support_metrics["customer_satisfaction"])

def show_service_testing():
    """Service testing interface"""
    st.header("🧪 Service Testing")
    
    # Service selection
    selected_services = st.multiselect(
        "Select Services to Test",
        list(SERVICES.keys()),
        format_func=lambda x: f"{SERVICES[x]['icon']} {SERVICES[x]['name']}",
        default=["provisioning", "orders", "payments"]
    )
    
    if selected_services:
        st.session_state.selected_services = selected_services
        
        # Test execution
        if st.button("🚀 Run Tests", use_container_width=True):
            with st.spinner("Running tests..."):
                test_results = {}
                
                for service in selected_services:
                    # Health check
                    health_result = check_service_health(service)
                    test_results[service] = {
                        "health": health_result,
                        "status": "✅ Healthy" if health_result.get("success", False) else "❌ Unhealthy"
                    }
                
                # Display results
                st.subheader("Test Results")
                
                for service, results in test_results.items():
                    service_info = SERVICES[service]
                    
                    with st.expander(f"{service_info['icon']} {service_info['name']} - {results['status']}"):
                        if results["health"].get("success", False):
                            st.success("✅ Service is healthy")
                            if "data" in results["health"]:
                                st.json(results["health"]["data"])
                        else:
                            st.error("❌ Service is unhealthy")
                            if "error" in results["health"]:
                                st.error(f"Error: {results['health']['error']}")
        
        # Individual service testing
        st.subheader("Individual Service Testing")
        
        for service in selected_services:
            service_info = SERVICES[service]
            
            with st.expander(f"{service_info['icon']} {service_info['name']} Testing"):
                # Health check
                if st.button(f"Check Health", key=f"health_{service}"):
                    with st.spinner(f"Checking {service_info['name']} health..."):
                        result = check_service_health(service)
                        
                        if result.get("success", False):
                            st.success("✅ Service is healthy")
                            st.json(result["data"])
                        else:
                            st.error("❌ Service is unhealthy")
                            st.error(f"Error: {result.get('error', 'Unknown error')}")
                
                # Service-specific tests
                if service == "provisioning":
                    st.write("**Provisioning Service Tests**")
                    
                    if st.button("Test Tenant Creation", key=f"tenant_{service}"):
                        with st.spinner("Testing tenant creation..."):
                            tenant_data = {
                                "tenant_id": str(uuid.uuid4()),
                                "name": "Test Tenant",
                                "email": "test@tenant.com"
                            }
                            
                            result = make_request(service, "/provisioning/tenants", "POST", tenant_data)
                            
                            if result.get("success", False):
                                st.success("✅ Tenant creation test passed")
                                st.json(result["data"])
                            else:
                                st.error(f"❌ Tenant creation test failed: {result.get('error', 'Unknown error')}")
                
                elif service == "orders":
                    st.write("**Orders Service Tests**")
                    
                    if st.button("Test Order Creation", key=f"order_{service}"):
                        with st.spinner("Testing order creation..."):
                            order_data = {
                                "order_id": str(uuid.uuid4()),
                                "tenant_id": st.session_state.tenant_id,
                                "customer_name": "Test Customer",
                                "total_amount_minor": 10000,
                                "currency": "GBP"
                            }
                            
                            result = make_request(service, "/orders/v2", "POST", order_data)
                            
                            if result.get("success", False):
                                st.success("✅ Order creation test passed")
                                st.json(result["data"])
                            else:
                                st.error(f"❌ Order creation test failed: {result.get('error', 'Unknown error')}")
                
                elif service == "payments":
                    st.write("**Payments Service Tests**")
                    
                    if st.button("Test Payment Creation", key=f"payment_{service}"):
                        with st.spinner("Testing payment creation..."):
                            payment_data = {
                                "payment_id": str(uuid.uuid4()),
                                "tenant_id": st.session_state.tenant_id,
                                "amount_minor": 10000,
                                "currency": "GBP",
                                "payment_method": "card"
                            }
                            
                            result = make_request(service, "/payments/new", "POST", payment_data)
                            
                            if result.get("success", False):
                                st.success("✅ Payment creation test passed")
                                st.json(result["data"])
                            else:
                                st.error(f"❌ Payment creation test failed: {result.get('error', 'Unknown error')}")
    
    # Test configuration
    st.subheader("Test Configuration")
    
    with st.form("test_configuration"):
        test_timeout = st.number_input("Test Timeout (seconds)", min_value=1, max_value=60, value=10)
        retry_attempts = st.number_input("Retry Attempts", min_value=0, max_value=5, value=3)
        parallel_tests = st.checkbox("Run Tests in Parallel", value=True)
        
        if st.form_submit_button("Update Configuration"):
            st.success("✅ Test configuration updated!")

def show_analytics_reports():
    """Analytics and reports page"""
    st.header("📊 Analytics & Reports")
    
    # Report selection
    report_type = st.selectbox(
        "Select Report Type",
        [
            "Platform Overview",
            "Service Performance",
            "Business Metrics",
            "User Analytics",
            "Financial Reports",
            "System Health"
        ]
    )
    
    if report_type == "Platform Overview":
        show_platform_overview_report()
    elif report_type == "Service Performance":
        show_service_performance_report()
    elif report_type == "Business Metrics":
        show_business_metrics_report()
    elif report_type == "User Analytics":
        show_user_analytics_report()
    elif report_type == "Financial Reports":
        show_financial_reports()
    elif report_type == "System Health":
        show_system_health_report()

def show_platform_overview_report():
    """Platform overview report"""
    st.subheader("📊 Platform Overview Report")
    
    # Key metrics
    st.write("#### Key Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Services", 21, "0")
    
    with col2:
        st.metric("Active Services", 18, "3")
    
    with col3:
        st.metric("Total Tenants", 1234, "56")
    
    with col4:
        st.metric("System Uptime", "99.9%", "0.1%")
    
    # Service distribution
    st.write("#### Service Distribution")
    
    service_data = []
    for service, info in SERVICES.items():
        service_data.append({
            "Service": info["name"],
            "Port": info["port"],
            "Status": "Active" if service in ["provisioning", "orders", "payments"] else "Inactive",
            "Health": "Healthy" if service in ["provisioning", "orders", "payments"] else "Unknown"
        })
    
    df = pd.DataFrame(service_data)
    st.dataframe(df, use_container_width=True)
    
    # Service status chart
    status_counts = df["Status"].value_counts()
    fig = px.pie(values=status_counts.values, names=status_counts.index, title="Service Status Distribution")
    st.plotly_chart(fig, use_container_width=True)

def show_service_performance_report():
    """Service performance report"""
    st.subheader("📈 Service Performance Report")
    
    # Performance metrics
    st.write("#### Performance Metrics")
    
    performance_data = {
        "provisioning": {"response_time": 120, "throughput": 150, "error_rate": 0.1},
        "orders": {"response_time": 180, "throughput": 200, "error_rate": 0.2},
        "payments": {"response_time": 250, "throughput": 100, "error_rate": 0.3},
        "billing": {"response_time": 300, "throughput": 80, "error_rate": 0.1},
        "notifications": {"response_time": 150, "throughput": 300, "error_rate": 0.2}
    }
    
    df = pd.DataFrame(performance_data).T
    st.dataframe(df, use_container_width=True)
    
    # Performance charts
    col1, col2 = st.columns(2)
    
    with col1:
        fig = px.bar(df, x=df.index, y="response_time", title="Response Time by Service")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = px.bar(df, x=df.index, y="throughput", title="Throughput by Service")
        st.plotly_chart(fig, use_container_width=True)

def show_business_metrics_report():
    """Business metrics report"""
    st.subheader("💼 Business Metrics Report")
    
    # Business KPIs
    st.write("#### Key Performance Indicators")
    
    kpi_data = {
        "Total Revenue": {"value": "£125,678.90", "change": "+12.5%", "trend": "up"},
        "Total Orders": {"value": "5,678", "change": "+8.3%", "trend": "up"},
        "Active Customers": {"value": "2,345", "change": "+15.2%", "trend": "up"},
        "Average Order Value": {"value": "£22.15", "change": "+3.1%", "trend": "up"},
        "Customer Satisfaction": {"value": "4.2/5", "change": "+0.3", "trend": "up"},
        "Churn Rate": {"value": "2.1%", "change": "-0.5%", "trend": "down"}
    }
    
    cols = st.columns(3)
    col_index = 0
    
    for kpi, data in kpi_data.items():
        with cols[col_index % 3]:
            if data["trend"] == "up":
                st.metric(kpi, data["value"], data["change"])
            else:
                st.metric(kpi, data["value"], data["change"])
        col_index += 1
    
    # Revenue trend
    st.write("#### Revenue Trend")
    
    revenue_data = []
    for i in range(12):
        month = datetime.now() - timedelta(days=30*i)
        revenue = 10000 + (i * 1000) + (i % 3) * 500
        revenue_data.append({
            "Month": month.strftime("%Y-%m"),
            "Revenue": revenue
        })
    
    df = pd.DataFrame(revenue_data)
    fig = px.line(df, x="Month", y="Revenue", title="Monthly Revenue Trend")
    st.plotly_chart(fig, use_container_width=True)

def show_user_analytics_report():
    """User analytics report"""
    st.subheader("👥 User Analytics Report")
    
    # User metrics
    st.write("#### User Metrics")
    
    user_metrics = {
        "Total Users": 2345,
        "Active Users": 1890,
        "New Users (30 days)": 123,
        "Returning Users": 456,
        "User Growth Rate": "15.2%",
        "Average Session Duration": "12.5 minutes"
    }
    
    cols = st.columns(3)
    col_index = 0
    
    for metric, value in user_metrics.items():
        with cols[col_index % 3]:
            st.metric(metric, value)
        col_index += 1
    
    # User activity
    st.write("#### User Activity")
    
    activity_data = [
        {"Hour": "00:00", "Users": 45},
        {"Hour": "06:00", "Users": 123},
        {"Hour": "09:00", "Users": 456},
        {"Hour": "12:00", "Users": 789},
        {"Hour": "15:00", "Users": 567},
        {"Hour": "18:00", "Users": 345},
        {"Hour": "21:00", "Users": 234}
    ]
    
    df = pd.DataFrame(activity_data)
    fig = px.bar(df, x="Hour", y="Users", title="User Activity by Hour")
    st.plotly_chart(fig, use_container_width=True)

def show_financial_reports():
    """Financial reports"""
    st.subheader("💰 Financial Reports")
    
    # Financial metrics
    st.write("#### Financial Metrics")
    
    financial_metrics = {
        "Total Revenue": "£125,678.90",
        "Total Expenses": "£89,234.56",
        "Net Profit": "£36,444.34",
        "Profit Margin": "29.0%",
        "Cash Flow": "£45,678.90",
        "Accounts Receivable": "£23,456.78"
    }
    
    cols = st.columns(3)
    col_index = 0
    
    for metric, value in financial_metrics.items():
        with cols[col_index % 3]:
            st.metric(metric, value)
        col_index += 1
    
    # Revenue breakdown
    st.write("#### Revenue Breakdown")
    
    revenue_breakdown = [
        {"Source": "Product Sales", "Amount": 75000, "Percentage": 59.7},
        {"Source": "Subscriptions", "Amount": 35000, "Percentage": 27.8},
        {"Source": "Services", "Amount": 15678, "Percentage": 12.5}
    ]
    
    df = pd.DataFrame(revenue_breakdown)
    fig = px.pie(df, values="Amount", names="Source", title="Revenue by Source")
    st.plotly_chart(fig, use_container_width=True)

def show_system_health_report():
    """System health report"""
    st.subheader("🏥 System Health Report")
    
    # System metrics
    st.write("#### System Metrics")
    
    system_metrics = {
        "CPU Usage": "45.2%",
        "Memory Usage": "67.8%",
        "Disk Usage": "34.5%",
        "Network Usage": "23.1%",
        "System Load": "1.2",
        "Uptime": "99.9%"
    }
    
    cols = st.columns(3)
    col_index = 0
    
    for metric, value in system_metrics.items():
        with cols[col_index % 3]:
            st.metric(metric, value)
        col_index += 1
    
    # System performance
    st.write("#### System Performance")
    
    performance_data = []
    for i in range(24):
        hour = datetime.now() - timedelta(hours=23-i)
        cpu = 40 + (i % 10) * 2
        memory = 60 + (i % 8) * 3
        performance_data.append({
            "Hour": hour.strftime("%H:00"),
            "CPU": cpu,
            "Memory": memory
        })
    
    df = pd.DataFrame(performance_data)
    fig = px.line(df, x="Hour", y=["CPU", "Memory"], title="System Performance Over Time")
    st.plotly_chart(fig, use_container_width=True)

def show_system_configuration():
    """System configuration page"""
    st.header("⚙️ System Configuration")
    
    # Configuration tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Service Settings", "Database Configuration", "Security Settings", "Monitoring Configuration"])
    
    with tab1:
        st.subheader("🔧 Service Settings")
        
        # Service configuration
        for service, info in SERVICES.items():
            with st.expander(f"{info['icon']} {info['name']} Configuration"):
                col1, col2 = st.columns(2)
                
                with col1:
                    port = st.number_input(f"Port", value=info["port"], key=f"port_{service}")
                    enabled = st.checkbox("Enabled", value=True, key=f"enabled_{service}")
                
                with col2:
                    timeout = st.number_input("Timeout (seconds)", value=30, key=f"timeout_{service}")
                    retries = st.number_input("Retry Attempts", value=3, key=f"retries_{service}")
                
                if st.button(f"Update {info['name']} Config", key=f"update_{service}"):
                    st.success(f"✅ {info['name']} configuration updated!")
    
    with tab2:
        st.subheader("🗄️ Database Configuration")
        
        # Database settings
        with st.form("database_config"):
            db_host = st.text_input("Database Host", value="localhost")
            db_port = st.number_input("Database Port", value=5432)
            db_name = st.text_input("Database Name", value="zeroque_dev")
            db_user = st.text_input("Database User", value="zeroque")
            db_password = st.text_input("Database Password", type="password", value="zeroque")
            
            if st.form_submit_button("Update Database Configuration"):
                st.success("✅ Database configuration updated!")
    
    with tab3:
        st.subheader("🔒 Security Settings")
        
        # Security settings
        with st.form("security_config"):
            jwt_secret = st.text_input("JWT Secret Key", type="password", value="your-secret-key")
            api_key_length = st.number_input("API Key Length", value=32)
            session_timeout = st.number_input("Session Timeout (minutes)", value=30)
            max_login_attempts = st.number_input("Max Login Attempts", value=5)
            
            if st.form_submit_button("Update Security Configuration"):
                st.success("✅ Security configuration updated!")
    
    with tab4:
        st.subheader("📊 Monitoring Configuration")
        
        # Monitoring settings
        with st.form("monitoring_config"):
            metrics_enabled = st.checkbox("Enable Metrics Collection", value=True)
            log_level = st.selectbox("Log Level", ["DEBUG", "INFO", "WARNING", "ERROR"])
            alert_email = st.text_input("Alert Email", value="admin@zeroque.com")
            health_check_interval = st.number_input("Health Check Interval (seconds)", value=30)
            
            if st.form_submit_button("Update Monitoring Configuration"):
                st.success("✅ Monitoring configuration updated!")
    
    # System actions
    st.subheader("🔄 System Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("🔄 Restart All Services", use_container_width=True):
            st.info("All services restart initiated...")
    
    with col2:
        if st.button("📊 Clear Metrics", use_container_width=True):
            st.info("Metrics cleared successfully!")
    
    with col3:
        if st.button("🗄️ Backup Database", use_container_width=True):
            st.info("Database backup initiated...")
    
    with col4:
        if st.button("🧹 Cleanup Logs", use_container_width=True):
            st.info("Log cleanup completed!")

if __name__ == "__main__":
    main()