#!/usr/bin/env python3
"""
ZeroQue Orders Service - Streamlit Demo
Order management and fulfillment
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Page configuration
st.set_page_config(
    page_title="ZeroQue Orders Service",
    page_icon="🛒",
    layout="wide"
)

# Service configuration
SERVICE_PORT = 8224
BASE_URL = f"http://localhost:{SERVICE_PORT}"

# Test data
TEST_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
TEST_SITE_ID = "550e8400-e29b-41d4-a716-446655440002"
TEST_STORE_ID = "550e8400-e29b-41d4-a716-446655440003"

def make_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
    """Make API request"""
    try:
        url = f"{BASE_URL}{endpoint}"
        
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=10)
        elif method == "PUT":
            response = requests.put(url, json=data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, timeout=10)
        else:
            return {"error": f"Unsupported method: {method}"}
        
        return {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
            "success": response.status_code < 400
        }
    except Exception as e:
        return {"error": str(e), "success": False}

def main():
    """Main application"""
    st.title("🛒 ZeroQue Orders Service")
    st.markdown("Order management and fulfillment")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        ["Dashboard", "Create Order", "Order List", "Order Details", "Analytics"]
    )
    
    # Initialize session state
    if "tenant_id" not in st.session_state:
        st.session_state.tenant_id = TEST_TENANT_ID
    if "user_id" not in st.session_state:
        st.session_state.user_id = TEST_USER_ID
    if "site_id" not in st.session_state:
        st.session_state.site_id = TEST_SITE_ID
    if "store_id" not in st.session_state:
        st.session_state.store_id = TEST_STORE_ID
    
    # Route to selected page
    if page == "Dashboard":
        show_dashboard()
    elif page == "Create Order":
        show_create_order()
    elif page == "Order List":
        show_order_list()
    elif page == "Order Details":
        show_order_details()
    elif page == "Analytics":
        show_analytics()

def show_dashboard():
    """Dashboard page"""
    st.header("📊 Orders Dashboard")
    
    # Service health
    st.subheader("Service Health")
    health_result = make_request("/health")
    
    if health_result["success"]:
        st.success("✅ Service is healthy")
        st.json(health_result["data"])
    else:
        st.error(f"❌ Service is unhealthy: {health_result.get('error', 'Unknown error')}")
    
    # Quick stats
    st.subheader("Quick Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Orders", "5,678", "234")
    
    with col2:
        st.metric("Pending Orders", "123", "-12")
    
    with col3:
        st.metric("Completed Orders", "4,567", "189")
    
    with col4:
        st.metric("Cancelled Orders", "234", "5")
    
    # Order status distribution
    st.subheader("Order Status Distribution")
    
    # Sample order status data
    status_data = [
        {"status": "pending", "count": 123, "percentage": 2.2},
        {"status": "confirmed", "count": 456, "percentage": 8.0},
        {"status": "processing", "count": 789, "percentage": 13.9},
        {"status": "shipped", "count": 1234, "percentage": 21.7},
        {"status": "delivered", "count": 2345, "percentage": 41.3},
        {"status": "cancelled", "count": 234, "percentage": 4.1},
        {"status": "returned", "count": 123, "percentage": 2.2}
    ]
    
    import pandas as pd
    import plotly.express as px
    
    df = pd.DataFrame(status_data)
    fig = px.pie(df, values="count", names="status", title="Order Status Distribution")
    st.plotly_chart(fig, use_container_width=True)
    
    # Recent orders
    st.subheader("Recent Orders")
    
    # Sample recent orders
    recent_orders = [
        {"order_id": "ORD-001", "customer": "John Doe", "status": "delivered", "amount": "£125.50", "date": "2024-01-15 10:30:00"},
        {"order_id": "ORD-002", "customer": "Jane Smith", "status": "shipped", "amount": "£89.99", "date": "2024-01-15 09:45:00"},
        {"order_id": "ORD-003", "customer": "Bob Johnson", "status": "processing", "amount": "£234.75", "date": "2024-01-15 08:20:00"},
        {"order_id": "ORD-004", "customer": "Alice Brown", "status": "confirmed", "amount": "£67.25", "date": "2024-01-15 07:15:00"},
        {"order_id": "ORD-005", "customer": "Charlie Wilson", "status": "pending", "amount": "£156.80", "date": "2024-01-15 06:30:00"}
    ]
    
    for order in recent_orders:
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.write(f"**{order['order_id']}**")
        
        with col2:
            st.write(order['customer'])
        
        with col3:
            if order['status'] == 'delivered':
                st.success(order['status'])
            elif order['status'] == 'shipped':
                st.info(order['status'])
            elif order['status'] == 'processing':
                st.warning(order['status'])
            else:
                st.write(order['status'])
        
        with col4:
            st.write(order['amount'])
        
        with col5:
            st.write(order['date'])

def show_create_order():
    """Create order page"""
    st.header("🛒 Create New Order")
    
    with st.form("create_order"):
        # Order basic information
        st.subheader("Order Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            order_type = st.selectbox("Order Type", ["retail", "wholesale", "bulk"])
            priority = st.selectbox("Priority", ["low", "medium", "high", "urgent"])
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@example.com")
        
        with col2:
            total_amount = st.number_input("Total Amount", min_value=0.01, value=100.00, step=0.01)
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
            payment_method = st.selectbox("Payment Method", ["card", "cash", "bank_transfer", "digital_wallet"])
            delivery_method = st.selectbox("Delivery Method", ["standard", "express", "overnight", "pickup"])
        
        # Order items
        st.subheader("Order Items")
        
        # Sample order items
        default_items = [
            {"product_id": "prod_123", "product_name": "Demo Product 1", "quantity": 2, "unit_price": 25.00},
            {"product_id": "prod_456", "product_name": "Demo Product 2", "quantity": 1, "unit_price": 50.00}
        ]
        
        items_json = st.text_area(
            "Order Items (JSON)",
            value=json.dumps(default_items, indent=2),
            height=200
        )
        
        # Additional information
        st.subheader("Additional Information")
        
        notes = st.text_area("Order Notes", value="This is a demo order for testing purposes.")
        shipping_address = st.text_area("Shipping Address", value="123 Demo Street, Demo City, DC 12345")
        
        if st.form_submit_button("Create Order"):
            try:
                items = json.loads(items_json)
                
                order_data = {
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "user_id": st.session_state.user_id,
                    "order_type": order_type,
                    "priority": priority,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "total_amount_minor": int(total_amount * 100),
                    "currency": currency,
                    "payment_method": payment_method,
                    "delivery_method": delivery_method,
                    "items": items,
                    "notes": notes,
                    "shipping_address": shipping_address
                }
                
                result = make_request("/orders/v2", "POST", order_data)
                
                if result["success"]:
                    st.success("✅ Order created successfully!")
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to create order: {result.get('error', 'Unknown error')}")
            except json.JSONDecodeError:
                st.error("❌ Invalid JSON in order items")
    
    # Order templates
    st.subheader("Order Templates")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Quick Order Template", use_container_width=True):
            st.info("Quick order template loaded")
    
    with col2:
        if st.button("Bulk Order Template", use_container_width=True):
            st.info("Bulk order template loaded")
    
    with col3:
        if st.button("Express Order Template", use_container_width=True):
            st.info("Express order template loaded")

def show_order_list():
    """Order list page"""
    st.header("📋 Order List")
    
    # Filters
    st.subheader("Filters")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        status_filter = st.selectbox("Status", ["All", "pending", "confirmed", "processing", "shipped", "delivered", "cancelled"])
    
    with col2:
        order_type_filter = st.selectbox("Order Type", ["All", "retail", "wholesale", "bulk"])
    
    with col3:
        priority_filter = st.selectbox("Priority", ["All", "low", "medium", "high", "urgent"])
    
    with col4:
        date_range = st.date_input("Date Range", value=[datetime.now().date(), datetime.now().date()])
    
    # Search
    search_query = st.text_input("Search Orders", placeholder="Order ID, customer name, or email")
    
    # Get orders
    if st.button("Get Orders"):
        result = make_request("/orders/v2", "GET")
        
        if result["success"]:
            orders = result["data"]
            if orders:
                st.success(f"✅ Found {len(orders)} orders")
                
                # Display orders in a table
                for order in orders:
                    with st.expander(f"Order: {order.get('order_id', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Customer:** {order.get('customer_name', 'N/A')}")
                            st.write(f"**Email:** {order.get('customer_email', 'N/A')}")
                            st.write(f"**Type:** {order.get('order_type', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Status:** {order.get('order_status', 'N/A')}")
                            st.write(f"**Priority:** {order.get('priority', 'N/A')}")
                            st.write(f"**Amount:** {order.get('total_amount_minor', 0) / 100:.2f} {order.get('currency', 'GBP')}")
                        
                        with col3:
                            st.write(f"**Payment:** {order.get('payment_method', 'N/A')}")
                            st.write(f"**Delivery:** {order.get('delivery_method', 'N/A')}")
                            st.write(f"**Created:** {order.get('created_at', 'N/A')}")
                        
                        # Order actions
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            if st.button("View Details", key=f"view_{order.get('order_id', 'unknown')}"):
                                st.info("Order details would be displayed here")
                        
                        with col2:
                            if st.button("Update Status", key=f"update_{order.get('order_id', 'unknown')}"):
                                st.info("Status update form would be displayed here")
                        
                        with col3:
                            if st.button("Cancel Order", key=f"cancel_{order.get('order_id', 'unknown')}"):
                                st.info("Order cancellation would be processed here")
                        
                        with col4:
                            if st.button("Print Invoice", key=f"print_{order.get('order_id', 'unknown')}"):
                                st.info("Invoice would be generated here")
            else:
                st.info("No orders found")
        else:
            st.error(f"❌ Failed to get orders: {result.get('error', 'Unknown error')}")
    
    # Order actions
    st.subheader("Bulk Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("Export Orders", use_container_width=True):
            st.info("Orders export initiated")
    
    with col2:
        if st.button("Update Statuses", use_container_width=True):
            st.info("Bulk status update initiated")
    
    with col3:
        if st.button("Generate Reports", use_container_width=True):
            st.info("Report generation initiated")
    
    with col4:
        if st.button("Send Notifications", use_container_width=True):
            st.info("Notification sending initiated")

def show_order_details():
    """Order details page"""
    st.header("📄 Order Details")
    
    # Order ID input
    order_id = st.text_input("Order ID", placeholder="Enter order ID to view details")
    
    if order_id and st.button("Get Order Details"):
        result = make_request(f"/orders/v2/{order_id}", "GET")
        
        if result["success"]:
            order = result["data"]
            st.success("✅ Order details retrieved!")
            
            # Order information
            st.subheader("Order Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Order ID:** {order.get('order_id', 'N/A')}")
                st.write(f"**Customer:** {order.get('customer_name', 'N/A')}")
                st.write(f"**Email:** {order.get('customer_email', 'N/A')}")
                st.write(f"**Type:** {order.get('order_type', 'N/A')}")
                st.write(f"**Priority:** {order.get('priority', 'N/A')}")
            
            with col2:
                st.write(f"**Status:** {order.get('order_status', 'N/A')}")
                st.write(f"**Amount:** {order.get('total_amount_minor', 0) / 100:.2f} {order.get('currency', 'GBP')}")
                st.write(f"**Payment:** {order.get('payment_method', 'N/A')}")
                st.write(f"**Delivery:** {order.get('delivery_method', 'N/A')}")
                st.write(f"**Created:** {order.get('created_at', 'N/A')}")
            
            # Order items
            st.subheader("Order Items")
            
            if "items" in order and order["items"]:
                for item in order["items"]:
                    with st.expander(f"Item: {item.get('product_name', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Product ID:** {item.get('product_id', 'N/A')}")
                            st.write(f"**Quantity:** {item.get('quantity', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Unit Price:** {item.get('unit_price', 0) / 100:.2f} {order.get('currency', 'GBP')}")
                            st.write(f"**Total:** {item.get('quantity', 0) * item.get('unit_price', 0) / 100:.2f} {order.get('currency', 'GBP')}")
                        
                        with col3:
                            st.write(f"**SKU:** {item.get('sku', 'N/A')}")
                            st.write(f"**Description:** {item.get('description', 'N/A')}")
            else:
                st.info("No items found for this order")
            
            # Order timeline
            st.subheader("Order Timeline")
            
            # Sample timeline
            timeline = [
                {"timestamp": "2024-01-15 10:30:00", "event": "Order Created", "description": "Order was created successfully"},
                {"timestamp": "2024-01-15 10:35:00", "event": "Payment Confirmed", "description": "Payment was processed and confirmed"},
                {"timestamp": "2024-01-15 11:00:00", "event": "Order Confirmed", "description": "Order was confirmed and sent to fulfillment"},
                {"timestamp": "2024-01-15 14:30:00", "event": "Processing", "description": "Order is being processed and prepared for shipment"},
                {"timestamp": "2024-01-16 09:00:00", "event": "Shipped", "description": "Order has been shipped and is in transit"}
            ]
            
            for event in timeline:
                st.write(f"**{event['timestamp']}** - {event['event']}: {event['description']}")
            
            # Order actions
            st.subheader("Order Actions")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("Update Status"):
                    st.info("Status update form would be displayed here")
            
            with col2:
                if st.button("Add Note"):
                    st.info("Note addition form would be displayed here")
            
            with col3:
                if st.button("Cancel Order"):
                    st.info("Order cancellation would be processed here")
            
            with col4:
                if st.button("Print Invoice"):
                    st.info("Invoice would be generated here")
        else:
            st.error(f"❌ Failed to get order details: {result.get('error', 'Unknown error')}")

def show_analytics():
    """Analytics page"""
    st.header("📈 Order Analytics")
    
    # Analytics tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Order Volume", "Revenue Analytics", "Customer Analytics", "Performance Metrics"])
    
    with tab1:
        st.subheader("Order Volume Analytics")
        
        # Sample order volume data
        volume_data = {
            "total_orders": 5678,
            "daily_average": 189.3,
            "weekly_average": 1325.2,
            "monthly_average": 5678,
            "growth_rate": 12.5,
            "peak_hours": [
                {"hour": "09:00", "orders": 45},
                {"hour": "10:00", "orders": 67},
                {"hour": "11:00", "orders": 89},
                {"hour": "12:00", "orders": 123},
                {"hour": "13:00", "orders": 98},
                {"hour": "14:00", "orders": 76},
                {"hour": "15:00", "orders": 54},
                {"hour": "16:00", "orders": 43}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Orders", volume_data["total_orders"])
        
        with col2:
            st.metric("Daily Average", volume_data["daily_average"])
        
        with col3:
            st.metric("Weekly Average", volume_data["weekly_average"])
        
        with col4:
            st.metric("Growth Rate", f"{volume_data['growth_rate']}%")
        
        # Peak hours chart
        import pandas as pd
        import plotly.express as px
        
        df = pd.DataFrame(volume_data["peak_hours"])
        fig = px.bar(df, x="hour", y="orders", title="Order Volume by Hour")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Revenue Analytics")
        
        # Sample revenue data
        revenue_data = {
            "total_revenue": 125678.90,
            "average_order_value": 22.15,
            "revenue_growth": 8.7,
            "top_products": [
                {"product": "Product A", "revenue": 12500.00, "orders": 456},
                {"product": "Product B", "revenue": 9800.00, "orders": 345},
                {"product": "Product C", "revenue": 7600.00, "orders": 234},
                {"product": "Product D", "revenue": 5400.00, "orders": 189},
                {"product": "Product E", "revenue": 3200.00, "orders": 123}
            ]
        }
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Revenue", f"£{revenue_data['total_revenue']:,.2f}")
        
        with col2:
            st.metric("Average Order Value", f"£{revenue_data['average_order_value']:.2f}")
        
        with col3:
            st.metric("Revenue Growth", f"{revenue_data['revenue_growth']}%")
        
        # Top products chart
        df = pd.DataFrame(revenue_data["top_products"])
        fig = px.bar(df, x="product", y="revenue", title="Top Products by Revenue")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Customer Analytics")
        
        # Sample customer data
        customer_data = {
            "total_customers": 2345,
            "new_customers": 123,
            "returning_customers": 456,
            "customer_satisfaction": 4.2,
            "top_customers": [
                {"customer": "John Doe", "orders": 45, "revenue": 2500.00},
                {"customer": "Jane Smith", "orders": 38, "revenue": 2200.00},
                {"customer": "Bob Johnson", "orders": 32, "revenue": 1800.00},
                {"customer": "Alice Brown", "orders": 28, "revenue": 1600.00},
                {"customer": "Charlie Wilson", "orders": 25, "revenue": 1400.00}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Customers", customer_data["total_customers"])
        
        with col2:
            st.metric("New Customers", customer_data["new_customers"])
        
        with col3:
            st.metric("Returning Customers", customer_data["returning_customers"])
        
        with col4:
            st.metric("Satisfaction", customer_data["customer_satisfaction"])
        
        # Top customers chart
        df = pd.DataFrame(customer_data["top_customers"])
        fig = px.bar(df, x="customer", y="revenue", title="Top Customers by Revenue")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.subheader("Performance Metrics")
        
        # Sample performance data
        performance_data = {
            "order_fulfillment_time": 2.5,
            "customer_satisfaction": 4.2,
            "order_accuracy": 98.5,
            "delivery_success_rate": 96.8,
            "return_rate": 3.2,
            "customer_complaints": 12,
            "system_uptime": 99.9,
            "api_response_time": 150
        }
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Fulfillment Time", f"{performance_data['order_fulfillment_time']} days")
            st.metric("Order Accuracy", f"{performance_data['order_accuracy']}%")
            st.metric("Delivery Success Rate", f"{performance_data['delivery_success_rate']}%")
            st.metric("System Uptime", f"{performance_data['system_uptime']}%")
        
        with col2:
            st.metric("Customer Satisfaction", f"{performance_data['customer_satisfaction']}/5")
            st.metric("Return Rate", f"{performance_data['return_rate']}%")
            st.metric("Customer Complaints", performance_data["customer_complaints"])
            st.metric("API Response Time", f"{performance_data['api_response_time']} ms")

if __name__ == "__main__":
    main()




