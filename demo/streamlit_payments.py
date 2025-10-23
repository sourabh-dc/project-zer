#!/usr/bin/env python3
"""
ZeroQue Payments Service - Streamlit Demo
Payment processing and management
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Page configuration
st.set_page_config(
    page_title="ZeroQue Payments Service",
    page_icon="💳",
    layout="wide"
)

# Service configuration
SERVICE_PORT = 8225
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
    st.title("💳 ZeroQue Payments Service")
    st.markdown("Payment processing and management")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        ["Dashboard", "Create Payment", "Payment List", "Payment Details", "Analytics"]
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
    elif page == "Create Payment":
        show_create_payment()
    elif page == "Payment List":
        show_payment_list()
    elif page == "Payment Details":
        show_payment_details()
    elif page == "Analytics":
        show_analytics()

def show_dashboard():
    """Dashboard page"""
    st.header("📊 Payments Dashboard")
    
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
        st.metric("Total Payments", "12,345", "567")
    
    with col2:
        st.metric("Successful Payments", "11,890", "523")
    
    with col3:
        st.metric("Failed Payments", "234", "12")
    
    with col4:
        st.metric("Pending Payments", "221", "32")
    
    # Payment status distribution
    st.subheader("Payment Status Distribution")
    
    # Sample payment status data
    status_data = [
        {"status": "pending", "count": 221, "percentage": 1.8},
        {"status": "processing", "count": 456, "percentage": 3.7},
        {"status": "completed", "count": 11890, "percentage": 96.3},
        {"status": "failed", "count": 234, "percentage": 1.9},
        {"status": "cancelled", "count": 123, "percentage": 1.0},
        {"status": "refunded", "count": 89, "percentage": 0.7}
    ]
    
    import pandas as pd
    import plotly.express as px
    
    df = pd.DataFrame(status_data)
    fig = px.pie(df, values="count", names="status", title="Payment Status Distribution")
    st.plotly_chart(fig, use_container_width=True)
    
    # Recent payments
    st.subheader("Recent Payments")
    
    # Sample recent payments
    recent_payments = [
        {"payment_id": "PAY-001", "customer": "John Doe", "status": "completed", "amount": "£125.50", "method": "card", "date": "2024-01-15 10:30:00"},
        {"payment_id": "PAY-002", "customer": "Jane Smith", "status": "processing", "amount": "£89.99", "method": "digital_wallet", "date": "2024-01-15 09:45:00"},
        {"payment_id": "PAY-003", "customer": "Bob Johnson", "status": "completed", "amount": "£234.75", "method": "bank_transfer", "date": "2024-01-15 08:20:00"},
        {"payment_id": "PAY-004", "customer": "Alice Brown", "status": "failed", "amount": "£67.25", "method": "card", "date": "2024-01-15 07:15:00"},
        {"payment_id": "PAY-005", "customer": "Charlie Wilson", "status": "pending", "amount": "£156.80", "method": "card", "date": "2024-01-15 06:30:00"}
    ]
    
    for payment in recent_payments:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        with col1:
            st.write(f"**{payment['payment_id']}**")
        
        with col2:
            st.write(payment['customer'])
        
        with col3:
            if payment['status'] == 'completed':
                st.success(payment['status'])
            elif payment['status'] == 'processing':
                st.info(payment['status'])
            elif payment['status'] == 'failed':
                st.error(payment['status'])
            else:
                st.write(payment['status'])
        
        with col4:
            st.write(payment['amount'])
        
        with col5:
            st.write(payment['method'])
        
        with col6:
            st.write(payment['date'])

def show_create_payment():
    """Create payment page"""
    st.header("💳 Create New Payment")
    
    with st.form("create_payment"):
        # Payment basic information
        st.subheader("Payment Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            payment_method = st.selectbox("Payment Method", ["card", "digital_wallet", "bank_transfer", "cash"])
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
            amount = st.number_input("Amount", min_value=0.01, value=100.00, step=0.01)
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@example.com")
        
        with col2:
            payment_type = st.selectbox("Payment Type", ["purchase", "refund", "partial_refund", "chargeback"])
            description = st.text_input("Description", value="Demo payment for testing")
            reference_id = st.text_input("Reference ID", value=f"REF-{uuid.uuid4().hex[:8].upper()}")
            metadata = st.text_area("Metadata (JSON)", value='{"order_id": "ORD-123", "product": "Demo Product"}')
        
        # Payment processing options
        st.subheader("Processing Options")
        
        col1, col2 = st.columns(2)
        
        with col1:
            auto_capture = st.checkbox("Auto Capture", value=True)
            save_payment_method = st.checkbox("Save Payment Method", value=False)
            send_receipt = st.checkbox("Send Receipt", value=True)
        
        with col2:
            retry_failed = st.checkbox("Retry Failed Payments", value=True)
            webhook_url = st.text_input("Webhook URL", value="https://example.com/webhook")
            timeout_seconds = st.number_input("Timeout (seconds)", min_value=30, max_value=300, value=120)
        
        # Card details (if card payment)
        if payment_method == "card":
            st.subheader("Card Details")
            
            col1, col2 = st.columns(2)
            
            with col1:
                card_number = st.text_input("Card Number", value="4242424242424242")
                expiry_month = st.selectbox("Expiry Month", list(range(1, 13)), index=11)
                expiry_year = st.selectbox("Expiry Year", list(range(2024, 2030)), index=0)
            
            with col2:
                cvv = st.text_input("CVV", value="123")
                cardholder_name = st.text_input("Cardholder Name", value="Demo Customer")
                billing_address = st.text_area("Billing Address", value="123 Demo Street, Demo City, DC 12345")
        
        # Digital wallet details (if digital wallet)
        elif payment_method == "digital_wallet":
            st.subheader("Digital Wallet Details")
            
            wallet_type = st.selectbox("Wallet Type", ["apple_pay", "google_pay", "paypal", "stripe"])
            wallet_token = st.text_input("Wallet Token", value="wallet_token_123")
        
        # Bank transfer details (if bank transfer)
        elif payment_method == "bank_transfer":
            st.subheader("Bank Transfer Details")
            
            col1, col2 = st.columns(2)
            
            with col1:
                bank_name = st.text_input("Bank Name", value="Demo Bank")
                account_number = st.text_input("Account Number", value="12345678")
                sort_code = st.text_input("Sort Code", value="12-34-56")
            
            with col2:
                account_holder_name = st.text_input("Account Holder Name", value="Demo Customer")
                reference = st.text_input("Transfer Reference", value="Demo Transfer")
        
        if st.form_submit_button("Create Payment"):
            try:
                payment_data = {
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "user_id": st.session_state.user_id,
                    "payment_method": payment_method,
                    "currency": currency,
                    "amount_minor": int(amount * 100),
                    "payment_type": payment_type,
                    "description": description,
                    "reference_id": reference_id,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "auto_capture": auto_capture,
                    "save_payment_method": save_payment_method,
                    "send_receipt": send_receipt,
                    "retry_failed": retry_failed,
                    "webhook_url": webhook_url,
                    "timeout_seconds": timeout_seconds,
                    "metadata": json.loads(metadata)
                }
                
                # Add payment method specific data
                if payment_method == "card":
                    payment_data["card_details"] = {
                        "card_number": card_number,
                        "expiry_month": expiry_month,
                        "expiry_year": expiry_year,
                        "cvv": cvv,
                        "cardholder_name": cardholder_name,
                        "billing_address": billing_address
                    }
                elif payment_method == "digital_wallet":
                    payment_data["wallet_details"] = {
                        "wallet_type": wallet_type,
                        "wallet_token": wallet_token
                    }
                elif payment_method == "bank_transfer":
                    payment_data["bank_details"] = {
                        "bank_name": bank_name,
                        "account_number": account_number,
                        "sort_code": sort_code,
                        "account_holder_name": account_holder_name,
                        "reference": reference
                    }
                
                result = make_request("/payments/new", "POST", payment_data)
                
                if result["success"]:
                    st.success("✅ Payment created successfully!")
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to create payment: {result.get('error', 'Unknown error')}")
            except json.JSONDecodeError:
                st.error("❌ Invalid JSON in metadata")
    
    # Payment templates
    st.subheader("Payment Templates")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Quick Payment Template", use_container_width=True):
            st.info("Quick payment template loaded")
    
    with col2:
        if st.button("Subscription Payment Template", use_container_width=True):
            st.info("Subscription payment template loaded")
    
    with col3:
        if st.button("Refund Template", use_container_width=True):
            st.info("Refund template loaded")

def show_payment_list():
    """Payment list page"""
    st.header("📋 Payment List")
    
    # Filters
    st.subheader("Filters")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        status_filter = st.selectbox("Status", ["All", "pending", "processing", "completed", "failed", "cancelled", "refunded"])
    
    with col2:
        method_filter = st.selectbox("Payment Method", ["All", "card", "digital_wallet", "bank_transfer", "cash"])
    
    with col3:
        type_filter = st.selectbox("Payment Type", ["All", "purchase", "refund", "partial_refund", "chargeback"])
    
    with col4:
        date_range = st.date_input("Date Range", value=[datetime.now().date(), datetime.now().date()])
    
    # Search
    search_query = st.text_input("Search Payments", placeholder="Payment ID, customer name, or reference")
    
    # Get payments
    if st.button("Get Payments"):
        result = make_request("/payments/new", "GET")
        
        if result["success"]:
            payments = result["data"]
            if payments:
                st.success(f"✅ Found {len(payments)} payments")
                
                # Display payments in a table
                for payment in payments:
                    with st.expander(f"Payment: {payment.get('payment_id', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Customer:** {payment.get('customer_name', 'N/A')}")
                            st.write(f"**Email:** {payment.get('customer_email', 'N/A')}")
                            st.write(f"**Method:** {payment.get('payment_method', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Status:** {payment.get('status', 'N/A')}")
                            st.write(f"**Type:** {payment.get('payment_type', 'N/A')}")
                            st.write(f"**Amount:** {payment.get('amount_minor', 0) / 100:.2f} {payment.get('currency', 'GBP')}")
                        
                        with col3:
                            st.write(f"**Reference:** {payment.get('reference_id', 'N/A')}")
                            st.write(f"**Description:** {payment.get('description', 'N/A')}")
                            st.write(f"**Created:** {payment.get('created_at', 'N/A')}")
                        
                        # Payment actions
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            if st.button("View Details", key=f"view_{payment.get('payment_id', 'unknown')}"):
                                st.info("Payment details would be displayed here")
                        
                        with col2:
                            if st.button("Capture Payment", key=f"capture_{payment.get('payment_id', 'unknown')}"):
                                st.info("Payment capture would be processed here")
                        
                        with col3:
                            if st.button("Refund Payment", key=f"refund_{payment.get('payment_id', 'unknown')}"):
                                st.info("Payment refund would be processed here")
                        
                        with col4:
                            if st.button("Cancel Payment", key=f"cancel_{payment.get('payment_id', 'unknown')}"):
                                st.info("Payment cancellation would be processed here")
            else:
                st.info("No payments found")
        else:
            st.error(f"❌ Failed to get payments: {result.get('error', 'Unknown error')}")
    
    # Payment actions
    st.subheader("Bulk Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("Export Payments", use_container_width=True):
            st.info("Payments export initiated")
    
    with col2:
        if st.button("Process Refunds", use_container_width=True):
            st.info("Bulk refund processing initiated")
    
    with col3:
        if st.button("Generate Reports", use_container_width=True):
            st.info("Report generation initiated")
    
    with col4:
        if st.button("Send Notifications", use_container_width=True):
            st.info("Notification sending initiated")

def show_payment_details():
    """Payment details page"""
    st.header("📄 Payment Details")
    
    # Payment ID input
    payment_id = st.text_input("Payment ID", placeholder="Enter payment ID to view details")
    
    if payment_id and st.button("Get Payment Details"):
        result = make_request(f"/payments/new/{payment_id}", "GET")
        
        if result["success"]:
            payment = result["data"]
            st.success("✅ Payment details retrieved!")
            
            # Payment information
            st.subheader("Payment Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Payment ID:** {payment.get('payment_id', 'N/A')}")
                st.write(f"**Customer:** {payment.get('customer_name', 'N/A')}")
                st.write(f"**Email:** {payment.get('customer_email', 'N/A')}")
                st.write(f"**Method:** {payment.get('payment_method', 'N/A')}")
                st.write(f"**Type:** {payment.get('payment_type', 'N/A')}")
            
            with col2:
                st.write(f"**Status:** {payment.get('status', 'N/A')}")
                st.write(f"**Amount:** {payment.get('amount_minor', 0) / 100:.2f} {payment.get('currency', 'GBP')}")
                st.write(f"**Reference:** {payment.get('reference_id', 'N/A')}")
                st.write(f"**Description:** {payment.get('description', 'N/A')}")
                st.write(f"**Created:** {payment.get('created_at', 'N/A')}")
            
            # Payment timeline
            st.subheader("Payment Timeline")
            
            # Sample timeline
            timeline = [
                {"timestamp": "2024-01-15 10:30:00", "event": "Payment Created", "description": "Payment was created successfully"},
                {"timestamp": "2024-01-15 10:31:00", "event": "Payment Processing", "description": "Payment is being processed"},
                {"timestamp": "2024-01-15 10:32:00", "event": "Payment Completed", "description": "Payment was completed successfully"},
                {"timestamp": "2024-01-15 10:33:00", "event": "Receipt Sent", "description": "Payment receipt was sent to customer"}
            ]
            
            for event in timeline:
                st.write(f"**{event['timestamp']}** - {event['event']}: {event['description']}")
            
            # Payment actions
            st.subheader("Payment Actions")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("Capture Payment"):
                    st.info("Payment capture would be processed here")
            
            with col2:
                if st.button("Refund Payment"):
                    st.info("Payment refund would be processed here")
            
            with col3:
                if st.button("Cancel Payment"):
                    st.info("Payment cancellation would be processed here")
            
            with col4:
                if st.button("Send Receipt"):
                    st.info("Receipt would be sent here")
        else:
            st.error(f"❌ Failed to get payment details: {result.get('error', 'Unknown error')}")

def show_analytics():
    """Analytics page"""
    st.header("📈 Payment Analytics")
    
    # Analytics tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Payment Volume", "Revenue Analytics", "Method Analytics", "Performance Metrics"])
    
    with tab1:
        st.subheader("Payment Volume Analytics")
        
        # Sample payment volume data
        volume_data = {
            "total_payments": 12345,
            "daily_average": 411.5,
            "weekly_average": 2880.5,
            "monthly_average": 12345,
            "growth_rate": 15.2,
            "peak_hours": [
                {"hour": "09:00", "payments": 67},
                {"hour": "10:00", "payments": 89},
                {"hour": "11:00", "payments": 123},
                {"hour": "12:00", "payments": 156},
                {"hour": "13:00", "payments": 134},
                {"hour": "14:00", "payments": 98},
                {"hour": "15:00", "payments": 76},
                {"hour": "16:00", "payments": 54}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Payments", volume_data["total_payments"])
        
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
        fig = px.bar(df, x="hour", y="payments", title="Payment Volume by Hour")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Revenue Analytics")
        
        # Sample revenue data
        revenue_data = {
            "total_revenue": 567890.12,
            "average_payment_value": 46.02,
            "revenue_growth": 12.8,
            "top_customers": [
                {"customer": "John Doe", "payments": 45, "revenue": 2500.00},
                {"customer": "Jane Smith", "payments": 38, "revenue": 2200.00},
                {"customer": "Bob Johnson", "payments": 32, "revenue": 1800.00},
                {"customer": "Alice Brown", "payments": 28, "revenue": 1600.00},
                {"customer": "Charlie Wilson", "payments": 25, "revenue": 1400.00}
            ]
        }
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Revenue", f"£{revenue_data['total_revenue']:,.2f}")
        
        with col2:
            st.metric("Average Payment Value", f"£{revenue_data['average_payment_value']:.2f}")
        
        with col3:
            st.metric("Revenue Growth", f"{revenue_data['revenue_growth']}%")
        
        # Top customers chart
        df = pd.DataFrame(revenue_data["top_customers"])
        fig = px.bar(df, x="customer", y="revenue", title="Top Customers by Revenue")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Payment Method Analytics")
        
        # Sample method data
        method_data = {
            "card_payments": 8500,
            "digital_wallet_payments": 2345,
            "bank_transfer_payments": 1234,
            "cash_payments": 266,
            "method_success_rates": [
                {"method": "card", "success_rate": 98.5},
                {"method": "digital_wallet", "success_rate": 97.2},
                {"method": "bank_transfer", "success_rate": 99.1},
                {"method": "cash", "success_rate": 100.0}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Card Payments", method_data["card_payments"])
        
        with col2:
            st.metric("Digital Wallet", method_data["digital_wallet_payments"])
        
        with col3:
            st.metric("Bank Transfer", method_data["bank_transfer_payments"])
        
        with col4:
            st.metric("Cash Payments", method_data["cash_payments"])
        
        # Method success rates chart
        df = pd.DataFrame(method_data["method_success_rates"])
        fig = px.bar(df, x="method", y="success_rate", title="Payment Method Success Rates")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.subheader("Performance Metrics")
        
        # Sample performance data
        performance_data = {
            "payment_success_rate": 97.8,
            "average_processing_time": 2.5,
            "customer_satisfaction": 4.3,
            "refund_rate": 2.1,
            "chargeback_rate": 0.3,
            "system_uptime": 99.9,
            "api_response_time": 120,
            "fraud_detection_rate": 0.1
        }
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Success Rate", f"{performance_data['payment_success_rate']}%")
            st.metric("Processing Time", f"{performance_data['average_processing_time']} seconds")
            st.metric("Customer Satisfaction", f"{performance_data['customer_satisfaction']}/5")
            st.metric("System Uptime", f"{performance_data['system_uptime']}%")
        
        with col2:
            st.metric("Refund Rate", f"{performance_data['refund_rate']}%")
            st.metric("Chargeback Rate", f"{performance_data['chargeback_rate']}%")
            st.metric("API Response Time", f"{performance_data['api_response_time']} ms")
            st.metric("Fraud Detection Rate", f"{performance_data['fraud_detection_rate']}%")

if __name__ == "__main__":
    main()




