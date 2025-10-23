#!/usr/bin/env python3
"""
ZeroQue Billing Service - Streamlit Demo
Billing and invoice management
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Page configuration
st.set_page_config(
    page_title="ZeroQue Billing Service",
    page_icon="🧾",
    layout="wide"
)

# Service configuration
SERVICE_PORT = 8214
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
    st.title("🧾 ZeroQue Billing Service")
    st.markdown("Billing and invoice management")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        ["Dashboard", "Create Invoice", "Invoice List", "Invoice Details", "Analytics"]
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
    elif page == "Create Invoice":
        show_create_invoice()
    elif page == "Invoice List":
        show_invoice_list()
    elif page == "Invoice Details":
        show_invoice_details()
    elif page == "Analytics":
        show_analytics()

def show_dashboard():
    """Dashboard page"""
    st.header("📊 Billing Dashboard")
    
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
        st.metric("Total Invoices", "8,456", "234")
    
    with col2:
        st.metric("Paid Invoices", "7,890", "189")
    
    with col3:
        st.metric("Pending Invoices", "456", "23")
    
    with col4:
        st.metric("Overdue Invoices", "110", "12")
    
    # Invoice status distribution
    st.subheader("Invoice Status Distribution")
    
    # Sample invoice status data
    status_data = [
        {"status": "draft", "count": 123, "percentage": 1.5},
        {"status": "sent", "count": 456, "percentage": 5.4},
        {"status": "paid", "count": 7890, "percentage": 93.3},
        {"status": "overdue", "count": 110, "percentage": 1.3},
        {"status": "cancelled", "count": 89, "percentage": 1.1},
        {"status": "refunded", "count": 45, "percentage": 0.5}
    ]
    
    import pandas as pd
    import plotly.express as px
    
    df = pd.DataFrame(status_data)
    fig = px.pie(df, values="count", names="status", title="Invoice Status Distribution")
    st.plotly_chart(fig, use_container_width=True)
    
    # Recent invoices
    st.subheader("Recent Invoices")
    
    # Sample recent invoices
    recent_invoices = [
        {"invoice_id": "INV-001", "customer": "John Doe", "status": "paid", "amount": "£125.50", "due_date": "2024-01-15", "date": "2024-01-15 10:30:00"},
        {"invoice_id": "INV-002", "customer": "Jane Smith", "status": "sent", "amount": "£89.99", "due_date": "2024-01-20", "date": "2024-01-15 09:45:00"},
        {"invoice_id": "INV-003", "customer": "Bob Johnson", "status": "overdue", "amount": "£234.75", "due_date": "2024-01-10", "date": "2024-01-15 08:20:00"},
        {"invoice_id": "INV-004", "customer": "Alice Brown", "status": "draft", "amount": "£67.25", "due_date": "2024-01-25", "date": "2024-01-15 07:15:00"},
        {"invoice_id": "INV-005", "customer": "Charlie Wilson", "status": "paid", "amount": "£156.80", "due_date": "2024-01-18", "date": "2024-01-15 06:30:00"}
    ]
    
    for invoice in recent_invoices:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        with col1:
            st.write(f"**{invoice['invoice_id']}**")
        
        with col2:
            st.write(invoice['customer'])
        
        with col3:
            if invoice['status'] == 'paid':
                st.success(invoice['status'])
            elif invoice['status'] == 'sent':
                st.info(invoice['status'])
            elif invoice['status'] == 'overdue':
                st.error(invoice['status'])
            else:
                st.write(invoice['status'])
        
        with col4:
            st.write(invoice['amount'])
        
        with col5:
            st.write(invoice['due_date'])
        
        with col6:
            st.write(invoice['date'])

def show_create_invoice():
    """Create invoice page"""
    st.header("🧾 Create New Invoice")
    
    with st.form("create_invoice"):
        # Invoice basic information
        st.subheader("Invoice Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            invoice_type = st.selectbox("Invoice Type", ["standard", "proforma", "credit_note", "debit_note"])
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
            due_days = st.number_input("Due Days", min_value=1, max_value=365, value=30)
            payment_terms = st.selectbox("Payment Terms", ["net_30", "net_15", "net_60", "due_on_receipt"])
        
        with col2:
            customer_name = st.text_input("Customer Name", value="Demo Customer")
            customer_email = st.text_input("Customer Email", value="customer@example.com")
            customer_address = st.text_area("Customer Address", value="123 Demo Street, Demo City, DC 12345")
            tax_rate = st.number_input("Tax Rate (%)", min_value=0.0, max_value=100.0, value=20.0, step=0.1)
        
        # Invoice items
        st.subheader("Invoice Items")
        
        # Sample invoice items
        default_items = [
            {"description": "Demo Product 1", "quantity": 2, "unit_price": 25.00, "tax_rate": 20.0},
            {"description": "Demo Product 2", "quantity": 1, "unit_price": 50.00, "tax_rate": 20.0}
        ]
        
        items_json = st.text_area(
            "Invoice Items (JSON)",
            value=json.dumps(default_items, indent=2),
            height=200
        )
        
        # Additional information
        st.subheader("Additional Information")
        
        notes = st.text_area("Invoice Notes", value="Thank you for your business!")
        footer_text = st.text_area("Footer Text", value="Payment terms: Net 30 days")
        reference = st.text_input("Reference", value=f"REF-{uuid.uuid4().hex[:8].upper()}")
        
        if st.form_submit_button("Create Invoice"):
            try:
                items = json.loads(items_json)
                
                # Calculate totals
                subtotal = sum(item["quantity"] * item["unit_price"] for item in items)
                total_tax = sum(item["quantity"] * item["unit_price"] * item["tax_rate"] / 100 for item in items)
                total_amount = subtotal + total_tax
                
                invoice_data = {
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": st.session_state.store_id,
                    "user_id": st.session_state.user_id,
                    "invoice_type": invoice_type,
                    "currency": currency,
                    "due_days": due_days,
                    "payment_terms": payment_terms,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "customer_address": customer_address,
                    "tax_rate": tax_rate,
                    "subtotal_minor": int(subtotal * 100),
                    "total_tax_minor": int(total_tax * 100),
                    "total_amount_minor": int(total_amount * 100),
                    "items": items,
                    "notes": notes,
                    "footer_text": footer_text,
                    "reference": reference
                }
                
                result = make_request("/billing/new/invoices", "POST", invoice_data)
                
                if result["success"]:
                    st.success("✅ Invoice created successfully!")
                    st.json(result["data"])
                else:
                    st.error(f"❌ Failed to create invoice: {result.get('error', 'Unknown error')}")
            except json.JSONDecodeError:
                st.error("❌ Invalid JSON in invoice items")
    
    # Invoice templates
    st.subheader("Invoice Templates")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Standard Invoice Template", use_container_width=True):
            st.info("Standard invoice template loaded")
    
    with col2:
        if st.button("Proforma Invoice Template", use_container_width=True):
            st.info("Proforma invoice template loaded")
    
    with col3:
        if st.button("Credit Note Template", use_container_width=True):
            st.info("Credit note template loaded")

def show_invoice_list():
    """Invoice list page"""
    st.header("📋 Invoice List")
    
    # Filters
    st.subheader("Filters")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        status_filter = st.selectbox("Status", ["All", "draft", "sent", "paid", "overdue", "cancelled", "refunded"])
    
    with col2:
        type_filter = st.selectbox("Invoice Type", ["All", "standard", "proforma", "credit_note", "debit_note"])
    
    with col3:
        currency_filter = st.selectbox("Currency", ["All", "GBP", "USD", "EUR"])
    
    with col4:
        date_range = st.date_input("Date Range", value=[datetime.now().date(), datetime.now().date()])
    
    # Search
    search_query = st.text_input("Search Invoices", placeholder="Invoice ID, customer name, or reference")
    
    # Get invoices
    if st.button("Get Invoices"):
        result = make_request("/billing/new/invoices", "GET")
        
        if result["success"]:
            invoices = result["data"]
            if invoices:
                st.success(f"✅ Found {len(invoices)} invoices")
                
                # Display invoices in a table
                for invoice in invoices:
                    with st.expander(f"Invoice: {invoice.get('invoice_id', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Customer:** {invoice.get('customer_name', 'N/A')}")
                            st.write(f"**Email:** {invoice.get('customer_email', 'N/A')}")
                            st.write(f"**Type:** {invoice.get('invoice_type', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Status:** {invoice.get('status', 'N/A')}")
                            st.write(f"**Amount:** {invoice.get('total_amount_minor', 0) / 100:.2f} {invoice.get('currency', 'GBP')}")
                            st.write(f"**Due Date:** {invoice.get('due_date', 'N/A')}")
                        
                        with col3:
                            st.write(f"**Reference:** {invoice.get('reference', 'N/A')}")
                            st.write(f"**Payment Terms:** {invoice.get('payment_terms', 'N/A')}")
                            st.write(f"**Created:** {invoice.get('created_at', 'N/A')}")
                        
                        # Invoice actions
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            if st.button("View Details", key=f"view_{invoice.get('invoice_id', 'unknown')}"):
                                st.info("Invoice details would be displayed here")
                        
                        with col2:
                            if st.button("Send Invoice", key=f"send_{invoice.get('invoice_id', 'unknown')}"):
                                st.info("Invoice sending would be processed here")
                        
                        with col3:
                            if st.button("Mark Paid", key=f"paid_{invoice.get('invoice_id', 'unknown')}"):
                                st.info("Invoice payment would be recorded here")
                        
                        with col4:
                            if st.button("Download PDF", key=f"download_{invoice.get('invoice_id', 'unknown')}"):
                                st.info("Invoice PDF would be downloaded here")
            else:
                st.info("No invoices found")
        else:
            st.error(f"❌ Failed to get invoices: {result.get('error', 'Unknown error')}")
    
    # Invoice actions
    st.subheader("Bulk Actions")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("Export Invoices", use_container_width=True):
            st.info("Invoices export initiated")
    
    with col2:
        if st.button("Send Reminders", use_container_width=True):
            st.info("Payment reminders sending initiated")
    
    with col3:
        if st.button("Generate Reports", use_container_width=True):
            st.info("Report generation initiated")
    
    with col4:
        if st.button("Process Payments", use_container_width=True):
            st.info("Payment processing initiated")

def show_invoice_details():
    """Invoice details page"""
    st.header("📄 Invoice Details")
    
    # Invoice ID input
    invoice_id = st.text_input("Invoice ID", placeholder="Enter invoice ID to view details")
    
    if invoice_id and st.button("Get Invoice Details"):
        result = make_request(f"/billing/new/invoices/{invoice_id}", "GET")
        
        if result["success"]:
            invoice = result["data"]
            st.success("✅ Invoice details retrieved!")
            
            # Invoice information
            st.subheader("Invoice Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Invoice ID:** {invoice.get('invoice_id', 'N/A')}")
                st.write(f"**Customer:** {invoice.get('customer_name', 'N/A')}")
                st.write(f"**Email:** {invoice.get('customer_email', 'N/A')}")
                st.write(f"**Type:** {invoice.get('invoice_type', 'N/A')}")
                st.write(f"**Status:** {invoice.get('status', 'N/A')}")
            
            with col2:
                st.write(f"**Amount:** {invoice.get('total_amount_minor', 0) / 100:.2f} {invoice.get('currency', 'GBP')}")
                st.write(f"**Due Date:** {invoice.get('due_date', 'N/A')}")
                st.write(f"**Reference:** {invoice.get('reference', 'N/A')}")
                st.write(f"**Payment Terms:** {invoice.get('payment_terms', 'N/A')}")
                st.write(f"**Created:** {invoice.get('created_at', 'N/A')}")
            
            # Invoice items
            st.subheader("Invoice Items")
            
            if "items" in invoice and invoice["items"]:
                for item in invoice["items"]:
                    with st.expander(f"Item: {item.get('description', 'Unknown')}"):
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            st.write(f"**Description:** {item.get('description', 'N/A')}")
                            st.write(f"**Quantity:** {item.get('quantity', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Unit Price:** {item.get('unit_price', 0) / 100:.2f} {invoice.get('currency', 'GBP')}")
                            st.write(f"**Tax Rate:** {item.get('tax_rate', 0)}%")
                        
                        with col3:
                            st.write(f"**Line Total:** {item.get('quantity', 0) * item.get('unit_price', 0) / 100:.2f} {invoice.get('currency', 'GBP')}")
                            st.write(f"**Tax Amount:** {item.get('quantity', 0) * item.get('unit_price', 0) * item.get('tax_rate', 0) / 10000:.2f} {invoice.get('currency', 'GBP')}")
                        
                        with col4:
                            st.write(f"**SKU:** {item.get('sku', 'N/A')}")
                            st.write(f"**Category:** {item.get('category', 'N/A')}")
            else:
                st.info("No items found for this invoice")
            
            # Invoice timeline
            st.subheader("Invoice Timeline")
            
            # Sample timeline
            timeline = [
                {"timestamp": "2024-01-15 10:30:00", "event": "Invoice Created", "description": "Invoice was created successfully"},
                {"timestamp": "2024-01-15 10:35:00", "event": "Invoice Sent", "description": "Invoice was sent to customer"},
                {"timestamp": "2024-01-16 14:20:00", "event": "Payment Received", "description": "Payment was received and processed"},
                {"timestamp": "2024-01-16 14:25:00", "event": "Invoice Paid", "description": "Invoice was marked as paid"}
            ]
            
            for event in timeline:
                st.write(f"**{event['timestamp']}** - {event['event']}: {event['description']}")
            
            # Invoice actions
            st.subheader("Invoice Actions")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("Send Invoice"):
                    st.info("Invoice sending would be processed here")
            
            with col2:
                if st.button("Mark Paid"):
                    st.info("Invoice payment would be recorded here")
            
            with col3:
                if st.button("Download PDF"):
                    st.info("Invoice PDF would be downloaded here")
            
            with col4:
                if st.button("Send Reminder"):
                    st.info("Payment reminder would be sent here")
        else:
            st.error(f"❌ Failed to get invoice details: {result.get('error', 'Unknown error')}")

def show_analytics():
    """Analytics page"""
    st.header("📈 Billing Analytics")
    
    # Analytics tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Revenue Analytics", "Payment Analytics", "Customer Analytics", "Performance Metrics"])
    
    with tab1:
        st.subheader("Revenue Analytics")
        
        # Sample revenue data
        revenue_data = {
            "total_revenue": 125678.90,
            "monthly_revenue": 12567.89,
            "revenue_growth": 12.5,
            "average_invoice_value": 45.67,
            "revenue_by_month": [
                {"month": "Jan", "revenue": 10500.00, "invoices": 230},
                {"month": "Feb", "revenue": 11200.00, "invoices": 245},
                {"month": "Mar", "revenue": 11800.00, "invoices": 258},
                {"month": "Apr", "revenue": 12500.00, "invoices": 272},
                {"month": "May", "revenue": 13200.00, "invoices": 289},
                {"month": "Jun", "revenue": 13800.00, "invoices": 302}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Revenue", f"£{revenue_data['total_revenue']:,.2f}")
        
        with col2:
            st.metric("Monthly Revenue", f"£{revenue_data['monthly_revenue']:,.2f}")
        
        with col3:
            st.metric("Revenue Growth", f"{revenue_data['revenue_growth']}%")
        
        with col4:
            st.metric("Average Invoice Value", f"£{revenue_data['average_invoice_value']:.2f}")
        
        # Revenue chart
        import pandas as pd
        import plotly.express as px
        
        df = pd.DataFrame(revenue_data["revenue_by_month"])
        fig = px.line(df, x="month", y="revenue", title="Revenue Trends Over Time")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Payment Analytics")
        
        # Sample payment data
        payment_data = {
            "total_payments": 7890,
            "average_payment_time": 18.5,
            "payment_success_rate": 94.2,
            "overdue_rate": 2.1,
            "payment_methods": [
                {"method": "card", "count": 4567, "percentage": 57.9},
                {"method": "bank_transfer", "count": 2345, "percentage": 29.7},
                {"method": "digital_wallet", "count": 678, "percentage": 8.6},
                {"method": "cash", "count": 300, "percentage": 3.8}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Payments", payment_data["total_payments"])
        
        with col2:
            st.metric("Average Payment Time", f"{payment_data['average_payment_time']} days")
        
        with col3:
            st.metric("Payment Success Rate", f"{payment_data['payment_success_rate']}%")
        
        with col4:
            st.metric("Overdue Rate", f"{payment_data['overdue_rate']}%")
        
        # Payment methods chart
        df = pd.DataFrame(payment_data["payment_methods"])
        fig = px.pie(df, values="count", names="method", title="Payment Methods Distribution")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Customer Analytics")
        
        # Sample customer data
        customer_data = {
            "total_customers": 2345,
            "active_customers": 1890,
            "average_customer_value": 67.89,
            "customer_retention_rate": 78.5,
            "top_customers": [
                {"customer": "John Doe", "invoices": 45, "revenue": 2500.00},
                {"customer": "Jane Smith", "invoices": 38, "revenue": 2200.00},
                {"customer": "Bob Johnson", "invoices": 32, "revenue": 1800.00},
                {"customer": "Alice Brown", "invoices": 28, "revenue": 1600.00},
                {"customer": "Charlie Wilson", "invoices": 25, "revenue": 1400.00}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Customers", customer_data["total_customers"])
        
        with col2:
            st.metric("Active Customers", customer_data["active_customers"])
        
        with col3:
            st.metric("Average Customer Value", f"£{customer_data['average_customer_value']:.2f}")
        
        with col4:
            st.metric("Customer Retention Rate", f"{customer_data['customer_retention_rate']}%")
        
        # Top customers chart
        df = pd.DataFrame(customer_data["top_customers"])
        fig = px.bar(df, x="customer", y="revenue", title="Top Customers by Revenue")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.subheader("Performance Metrics")
        
        # Sample performance data
        performance_data = {
            "invoice_processing_time": 2.5,
            "payment_processing_time": 1.8,
            "customer_satisfaction": 4.2,
            "system_uptime": 99.9,
            "api_response_time": 150,
            "error_rate": 0.1,
            "automation_rate": 85.3,
            "compliance_rate": 98.7
        }
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Invoice Processing Time", f"{performance_data['invoice_processing_time']} days")
            st.metric("Payment Processing Time", f"{performance_data['payment_processing_time']} days")
            st.metric("Customer Satisfaction", f"{performance_data['customer_satisfaction']}/5")
            st.metric("System Uptime", f"{performance_data['system_uptime']}%")
        
        with col2:
            st.metric("API Response Time", f"{performance_data['api_response_time']} ms")
            st.metric("Error Rate", f"{performance_data['error_rate']}%")
            st.metric("Automation Rate", f"{performance_data['automation_rate']}%")
            st.metric("Compliance Rate", f"{performance_data['compliance_rate']}%")

if __name__ == "__main__":
    main()




