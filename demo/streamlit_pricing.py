#!/usr/bin/env python3
"""
ZeroQue Pricing Service - Streamlit Demo
Dynamic pricing and price management
"""

import streamlit as st
import requests
import json
import uuid
from datetime import datetime
from typing import Dict, Any, List

# Page configuration
st.set_page_config(
    page_title="ZeroQue Pricing Service",
    page_icon="💰",
    layout="wide"
)

# Service configuration
SERVICE_PORT = 8226
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
    st.title("💰 ZeroQue Pricing Service")
    st.markdown("Dynamic pricing and price management")
    
    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox(
        "Select Page",
        ["Dashboard", "Price Calculator", "Price Rules", "Price Books", "Analytics"]
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
    elif page == "Price Calculator":
        show_price_calculator()
    elif page == "Price Rules":
        show_price_rules()
    elif page == "Price Books":
        show_price_books()
    elif page == "Analytics":
        show_analytics()

def show_dashboard():
    """Dashboard page"""
    st.header("📊 Pricing Dashboard")
    
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
        st.metric("Active Price Rules", "156", "12")
    
    with col2:
        st.metric("Price Books", "23", "3")
    
    with col3:
        st.metric("Calculations Today", "2,345", "189")
    
    with col4:
        st.metric("Average Price", "£45.67", "£2.34")
    
    # Price distribution
    st.subheader("Price Distribution")
    
    # Sample price distribution data
    price_data = [
        {"range": "£0-£10", "count": 234, "percentage": 15.0},
        {"range": "£10-£25", "count": 456, "percentage": 29.2},
        {"range": "£25-£50", "count": 567, "percentage": 36.3},
        {"range": "£50-£100", "count": 234, "percentage": 15.0},
        {"range": "£100+", "count": 89, "percentage": 5.7}
    ]
    
    import pandas as pd
    import plotly.express as px
    
    df = pd.DataFrame(price_data)
    fig = px.pie(df, values="count", names="range", title="Price Distribution")
    st.plotly_chart(fig, use_container_width=True)
    
    # Recent price calculations
    st.subheader("Recent Price Calculations")
    
    # Sample recent calculations
    recent_calculations = [
        {"product": "Product A", "base_price": "£25.00", "final_price": "£22.50", "discount": "10%", "rule": "Bulk Discount", "timestamp": "2024-01-15 10:30:00"},
        {"product": "Product B", "base_price": "£50.00", "final_price": "£45.00", "discount": "10%", "rule": "Member Discount", "timestamp": "2024-01-15 10:25:00"},
        {"product": "Product C", "base_price": "£75.00", "final_price": "£75.00", "discount": "0%", "rule": "No Discount", "timestamp": "2024-01-15 10:20:00"},
        {"product": "Product D", "base_price": "£100.00", "final_price": "£85.00", "discount": "15%", "rule": "Seasonal Sale", "timestamp": "2024-01-15 10:15:00"},
        {"product": "Product E", "base_price": "£30.00", "final_price": "£27.00", "discount": "10%", "rule": "First Time Buyer", "timestamp": "2024-01-15 10:10:00"}
    ]
    
    for calc in recent_calculations:
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        with col1:
            st.write(f"**{calc['product']}**")
        
        with col2:
            st.write(calc['base_price'])
        
        with col3:
            st.write(calc['final_price'])
        
        with col4:
            if calc['discount'] == "0%":
                st.write(calc['discount'])
            else:
                st.success(calc['discount'])
        
        with col5:
            st.write(calc['rule'])
        
        with col6:
            st.write(calc['timestamp'])

def show_price_calculator():
    """Price calculator page"""
    st.header("🧮 Price Calculator")
    
    with st.form("price_calculator"):
        # Product information
        st.subheader("Product Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            product_id = st.text_input("Product ID", value="prod_123")
            product_name = st.text_input("Product Name", value="Demo Product")
            base_price = st.number_input("Base Price", min_value=0.01, value=50.00, step=0.01)
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
        
        with col2:
            category = st.selectbox("Category", ["electronics", "clothing", "books", "home", "sports"])
            brand = st.text_input("Brand", value="Demo Brand")
            sku = st.text_input("SKU", value="SKU-123")
            supplier = st.selectbox("Supplier", ["Supplier A", "Supplier B", "Supplier C"])
        
        # Customer information
        st.subheader("Customer Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            customer_type = st.selectbox("Customer Type", ["individual", "business", "wholesale", "retailer"])
            customer_tier = st.selectbox("Customer Tier", ["bronze", "silver", "gold", "platinum"])
            is_new_customer = st.checkbox("New Customer", value=False)
            is_vip_customer = st.checkbox("VIP Customer", value=False)
        
        with col2:
            order_quantity = st.number_input("Order Quantity", min_value=1, value=1)
            order_value = st.number_input("Order Value", min_value=0.01, value=100.00, step=0.01)
            payment_method = st.selectbox("Payment Method", ["card", "cash", "bank_transfer", "digital_wallet"])
            delivery_method = st.selectbox("Delivery Method", ["standard", "express", "overnight", "pickup"])
        
        # Context information
        st.subheader("Context Information")
        
        col1, col2 = st.columns(2)
        
        with col1:
            time_of_day = st.selectbox("Time of Day", ["morning", "afternoon", "evening", "night"])
            day_of_week = st.selectbox("Day of Week", ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])
            season = st.selectbox("Season", ["spring", "summer", "autumn", "winter"])
            weather = st.selectbox("Weather", ["sunny", "cloudy", "rainy", "snowy"])
        
        with col2:
            location = st.text_input("Location", value="London, UK")
            store_id = st.text_input("Store ID", value=st.session_state.store_id)
            sales_channel = st.selectbox("Sales Channel", ["online", "in_store", "mobile", "phone"])
            promotion_code = st.text_input("Promotion Code", value="")
        
        if st.form_submit_button("Calculate Price"):
            try:
                calculation_data = {
                    "tenant_id": st.session_state.tenant_id,
                    "site_id": st.session_state.site_id,
                    "store_id": store_id,
                    "product_id": product_id,
                    "product_name": product_name,
                    "base_price_minor": int(base_price * 100),
                    "currency": currency,
                    "category": category,
                    "brand": brand,
                    "sku": sku,
                    "supplier": supplier,
                    "customer_type": customer_type,
                    "customer_tier": customer_tier,
                    "is_new_customer": is_new_customer,
                    "is_vip_customer": is_vip_customer,
                    "order_quantity": order_quantity,
                    "order_value_minor": int(order_value * 100),
                    "payment_method": payment_method,
                    "delivery_method": delivery_method,
                    "time_of_day": time_of_day,
                    "day_of_week": day_of_week,
                    "season": season,
                    "weather": weather,
                    "location": location,
                    "sales_channel": sales_channel,
                    "promotion_code": promotion_code
                }
                
                result = make_request("/pricing/v2/calculate", "POST", calculation_data)
                
                if result["success"]:
                    st.success("✅ Price calculated successfully!")
                    
                    # Display calculation results
                    calculation_result = result["data"]
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Base Price", f"£{base_price:.2f}")
                    
                    with col2:
                        final_price = calculation_result.get("final_price_minor", 0) / 100
                        st.metric("Final Price", f"£{final_price:.2f}")
                    
                    with col3:
                        discount = calculation_result.get("discount_percentage", 0)
                        st.metric("Discount", f"{discount}%")
                    
                    # Show detailed breakdown
                    st.subheader("Price Breakdown")
                    
                    if "price_breakdown" in calculation_result:
                        breakdown = calculation_result["price_breakdown"]
                        
                        for item in breakdown:
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                st.write(f"**{item.get('component', 'Unknown')}**")
                            
                            with col2:
                                amount = item.get("amount_minor", 0) / 100
                                st.write(f"£{amount:.2f}")
                            
                            with col3:
                                st.write(item.get("description", "N/A"))
                    
                    # Show applied rules
                    if "applied_rules" in calculation_result:
                        st.subheader("Applied Rules")
                        
                        for rule in calculation_result["applied_rules"]:
                            st.write(f"• **{rule.get('rule_name', 'Unknown')}**: {rule.get('description', 'N/A')}")
                    
                    st.json(calculation_result)
                else:
                    st.error(f"❌ Failed to calculate price: {result.get('error', 'Unknown error')}")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
    
    # Quick calculation templates
    st.subheader("Quick Calculation Templates")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("Bulk Order Template", use_container_width=True):
            st.info("Bulk order pricing template loaded")
    
    with col2:
        if st.button("VIP Customer Template", use_container_width=True):
            st.info("VIP customer pricing template loaded")
    
    with col3:
        if st.button("Seasonal Sale Template", use_container_width=True):
            st.info("Seasonal sale pricing template loaded")

def show_price_rules():
    """Price rules page"""
    st.header("📋 Price Rules")
    
    # Create new rule
    with st.expander("Create New Price Rule"):
        with st.form("create_price_rule"):
            st.subheader("Rule Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                rule_name = st.text_input("Rule Name", value="Demo Rule")
                rule_type = st.selectbox("Rule Type", ["discount", "markup", "fixed_price", "percentage"])
                priority = st.number_input("Priority", min_value=1, max_value=100, value=50)
                is_active = st.checkbox("Active", value=True)
            
            with col2:
                condition_type = st.selectbox("Condition Type", ["customer_type", "order_quantity", "order_value", "time_based", "location_based"])
                condition_value = st.text_input("Condition Value", value="individual")
                action_type = st.selectbox("Action Type", ["apply_discount", "apply_markup", "set_fixed_price"])
                action_value = st.number_input("Action Value", min_value=0.0, value=10.0, step=0.1)
            
            # Rule conditions
            st.subheader("Rule Conditions")
            
            conditions_json = st.text_area(
                "Conditions (JSON)",
                value=json.dumps({
                    "customer_type": "individual",
                    "order_quantity": {"min": 1, "max": 10},
                    "order_value": {"min": 0, "max": 1000}
                }, indent=2),
                height=150
            )
            
            # Rule actions
            st.subheader("Rule Actions")
            
            actions_json = st.text_area(
                "Actions (JSON)",
                value=json.dumps({
                    "discount_percentage": 10,
                    "discount_amount_minor": 500,
                    "max_discount_minor": 1000
                }, indent=2),
                height=150
            )
            
            if st.form_submit_button("Create Rule"):
                try:
                    rule_data = {
                        "tenant_id": st.session_state.tenant_id,
                        "rule_name": rule_name,
                        "rule_type": rule_type,
                        "priority": priority,
                        "is_active": is_active,
                        "condition_type": condition_type,
                        "condition_value": condition_value,
                        "action_type": action_type,
                        "action_value": action_value,
                        "conditions": json.loads(conditions_json),
                        "actions": json.loads(actions_json)
                    }
                    
                    result = make_request("/pricing/v2/rules", "POST", rule_data)
                    
                    if result["success"]:
                        st.success("✅ Price rule created successfully!")
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to create price rule: {result.get('error', 'Unknown error')}")
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON in conditions or actions")
    
    # List existing rules
    st.subheader("Existing Price Rules")
    
    if st.button("Get Price Rules"):
        result = make_request("/pricing/v2/rules", "GET")
        
        if result["success"]:
            rules = result["data"]
            if rules:
                st.success(f"✅ Found {len(rules)} price rules")
                
                for rule in rules:
                    with st.expander(f"Rule: {rule.get('rule_name', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Type:** {rule.get('rule_type', 'N/A')}")
                            st.write(f"**Priority:** {rule.get('priority', 'N/A')}")
                            st.write(f"**Active:** {rule.get('is_active', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Condition:** {rule.get('condition_type', 'N/A')}")
                            st.write(f"**Value:** {rule.get('condition_value', 'N/A')}")
                            st.write(f"**Action:** {rule.get('action_type', 'N/A')}")
                        
                        with col3:
                            st.write(f"**Action Value:** {rule.get('action_value', 'N/A')}")
                            st.write(f"**Created:** {rule.get('created_at', 'N/A')}")
                            st.write(f"**Updated:** {rule.get('updated_at', 'N/A')}")
                        
                        # Rule actions
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            if st.button("Edit Rule", key=f"edit_{rule.get('rule_id', 'unknown')}"):
                                st.info("Rule editing form would be displayed here")
                        
                        with col2:
                            if st.button("Test Rule", key=f"test_{rule.get('rule_id', 'unknown')}"):
                                st.info("Rule testing would be performed here")
                        
                        with col3:
                            if st.button("Deactivate Rule", key=f"deactivate_{rule.get('rule_id', 'unknown')}"):
                                st.info("Rule deactivation would be processed here")
                        
                        with col4:
                            if st.button("Delete Rule", key=f"delete_{rule.get('rule_id', 'unknown')}"):
                                st.info("Rule deletion would be processed here")
            else:
                st.info("No price rules found")
        else:
            st.error(f"❌ Failed to get price rules: {result.get('error', 'Unknown error')}")

def show_price_books():
    """Price books page"""
    st.header("📚 Price Books")
    
    # Create new price book
    with st.expander("Create New Price Book"):
        with st.form("create_price_book"):
            st.subheader("Price Book Information")
            
            col1, col2 = st.columns(2)
            
            with col1:
                book_name = st.text_input("Book Name", value="Demo Price Book")
                book_type = st.selectbox("Book Type", ["standard", "wholesale", "retail", "promotional"])
                currency = st.selectbox("Currency", ["GBP", "USD", "EUR"])
                is_active = st.checkbox("Active", value=True)
            
            with col2:
                valid_from = st.date_input("Valid From", value=datetime.now().date())
                valid_until = st.date_input("Valid Until", value=datetime.now().date())
                description = st.text_area("Description", value="Demo price book for testing")
            
            # Price book items
            st.subheader("Price Book Items")
            
            # Sample price book items
            default_items = [
                {"product_id": "prod_123", "product_name": "Demo Product 1", "price_minor": 2500, "currency": "GBP"},
                {"product_id": "prod_456", "product_name": "Demo Product 2", "price_minor": 5000, "currency": "GBP"}
            ]
            
            items_json = st.text_area(
                "Price Book Items (JSON)",
                value=json.dumps(default_items, indent=2),
                height=200
            )
            
            if st.form_submit_button("Create Price Book"):
                try:
                    items = json.loads(items_json)
                    
                    price_book_data = {
                        "tenant_id": st.session_state.tenant_id,
                        "book_name": book_name,
                        "book_type": book_type,
                        "currency": currency,
                        "is_active": is_active,
                        "valid_from": valid_from.isoformat(),
                        "valid_until": valid_until.isoformat(),
                        "description": description,
                        "items": items
                    }
                    
                    result = make_request("/pricing/v2/pricebooks", "POST", price_book_data)
                    
                    if result["success"]:
                        st.success("✅ Price book created successfully!")
                        st.json(result["data"])
                    else:
                        st.error(f"❌ Failed to create price book: {result.get('error', 'Unknown error')}")
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON in price book items")
    
    # List existing price books
    st.subheader("Existing Price Books")
    
    if st.button("Get Price Books"):
        result = make_request("/pricing/v2/pricebooks", "GET")
        
        if result["success"]:
            price_books = result["data"]
            if price_books:
                st.success(f"✅ Found {len(price_books)} price books")
                
                for book in price_books:
                    with st.expander(f"Price Book: {book.get('book_name', 'Unknown')}"):
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.write(f"**Type:** {book.get('book_type', 'N/A')}")
                            st.write(f"**Currency:** {book.get('currency', 'N/A')}")
                            st.write(f"**Active:** {book.get('is_active', 'N/A')}")
                        
                        with col2:
                            st.write(f"**Valid From:** {book.get('valid_from', 'N/A')}")
                            st.write(f"**Valid Until:** {book.get('valid_until', 'N/A')}")
                            st.write(f"**Items Count:** {len(book.get('items', []))}")
                        
                        with col3:
                            st.write(f"**Created:** {book.get('created_at', 'N/A')}")
                            st.write(f"**Updated:** {book.get('updated_at', 'N/A')}")
                        
                        # Price book actions
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            if st.button("View Items", key=f"view_{book.get('book_id', 'unknown')}"):
                                st.info("Price book items would be displayed here")
                        
                        with col2:
                            if st.button("Edit Book", key=f"edit_{book.get('book_id', 'unknown')}"):
                                st.info("Price book editing form would be displayed here")
                        
                        with col3:
                            if st.button("Export Book", key=f"export_{book.get('book_id', 'unknown')}"):
                                st.info("Price book export would be initiated here")
                        
                        with col4:
                            if st.button("Delete Book", key=f"delete_{book.get('book_id', 'unknown')}"):
                                st.info("Price book deletion would be processed here")
            else:
                st.info("No price books found")
        else:
            st.error(f"❌ Failed to get price books: {result.get('error', 'Unknown error')}")

def show_analytics():
    """Analytics page"""
    st.header("📈 Pricing Analytics")
    
    # Analytics tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Price Trends", "Rule Performance", "Customer Impact", "Revenue Impact"])
    
    with tab1:
        st.subheader("Price Trends Analytics")
        
        # Sample price trend data
        trend_data = {
            "average_price": 45.67,
            "price_volatility": 12.3,
            "trend_direction": "up",
            "trend_strength": 0.75,
            "price_changes": [
                {"date": "2024-01-01", "price": 42.50, "change": 0},
                {"date": "2024-01-02", "price": 43.20, "change": 1.65},
                {"date": "2024-01-03", "price": 44.10, "change": 2.08},
                {"date": "2024-01-04", "price": 45.30, "change": 2.72},
                {"date": "2024-01-05", "price": 46.80, "change": 3.31},
                {"date": "2024-01-06", "price": 47.50, "change": 1.50},
                {"date": "2024-01-07", "price": 48.20, "change": 1.47}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Average Price", f"£{trend_data['average_price']:.2f}")
        
        with col2:
            st.metric("Price Volatility", f"{trend_data['price_volatility']}%")
        
        with col3:
            st.metric("Trend Direction", trend_data['trend_direction'].title())
        
        with col4:
            st.metric("Trend Strength", f"{trend_data['trend_strength']:.2f}")
        
        # Price trend chart
        import pandas as pd
        import plotly.express as px
        
        df = pd.DataFrame(trend_data["price_changes"])
        fig = px.line(df, x="date", y="price", title="Price Trends Over Time")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader("Rule Performance Analytics")
        
        # Sample rule performance data
        rule_performance = {
            "total_rules": 156,
            "active_rules": 134,
            "rules_triggered": 2345,
            "success_rate": 94.2,
            "top_rules": [
                {"rule": "Bulk Discount", "triggered": 456, "success_rate": 98.5, "revenue_impact": 12500.00},
                {"rule": "Member Discount", "triggered": 345, "success_rate": 96.8, "revenue_impact": 8900.00},
                {"rule": "Seasonal Sale", "triggered": 234, "success_rate": 97.2, "revenue_impact": 6700.00},
                {"rule": "First Time Buyer", "triggered": 189, "success_rate": 95.1, "revenue_impact": 4500.00},
                {"rule": "VIP Discount", "triggered": 123, "success_rate": 99.2, "revenue_impact": 3200.00}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Rules", rule_performance["total_rules"])
        
        with col2:
            st.metric("Active Rules", rule_performance["active_rules"])
        
        with col3:
            st.metric("Rules Triggered", rule_performance["rules_triggered"])
        
        with col4:
            st.metric("Success Rate", f"{rule_performance['success_rate']}%")
        
        # Top rules chart
        df = pd.DataFrame(rule_performance["top_rules"])
        fig = px.bar(df, x="rule", y="revenue_impact", title="Top Rules by Revenue Impact")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader("Customer Impact Analytics")
        
        # Sample customer impact data
        customer_impact = {
            "total_customers": 2345,
            "customers_with_discounts": 1234,
            "average_discount": 12.5,
            "customer_satisfaction": 4.2,
            "customer_segments": [
                {"segment": "VIP", "count": 234, "avg_discount": 18.5, "satisfaction": 4.5},
                {"segment": "Gold", "count": 456, "avg_discount": 15.2, "satisfaction": 4.3},
                {"segment": "Silver", "count": 678, "avg_discount": 12.1, "satisfaction": 4.1},
                {"segment": "Bronze", "count": 567, "avg_discount": 8.7, "satisfaction": 3.9},
                {"segment": "New", "count": 410, "avg_discount": 10.3, "satisfaction": 4.0}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Customers", customer_impact["total_customers"])
        
        with col2:
            st.metric("Customers with Discounts", customer_impact["customers_with_discounts"])
        
        with col3:
            st.metric("Average Discount", f"{customer_impact['average_discount']}%")
        
        with col4:
            st.metric("Customer Satisfaction", f"{customer_impact['customer_satisfaction']}/5")
        
        # Customer segments chart
        df = pd.DataFrame(customer_impact["customer_segments"])
        fig = px.bar(df, x="segment", y="avg_discount", title="Average Discount by Customer Segment")
        st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.subheader("Revenue Impact Analytics")
        
        # Sample revenue impact data
        revenue_impact = {
            "total_revenue": 567890.12,
            "revenue_from_discounts": 45678.90,
            "revenue_growth": 15.2,
            "profit_margin": 23.5,
            "revenue_by_channel": [
                {"channel": "Online", "revenue": 234567.89, "growth": 18.5},
                {"channel": "In-Store", "revenue": 189234.56, "growth": 12.3},
                {"channel": "Mobile", "revenue": 98765.43, "growth": 25.7},
                {"channel": "Phone", "revenue": 45322.24, "growth": 8.9}
            ]
        }
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Revenue", f"£{revenue_impact['total_revenue']:,.2f}")
        
        with col2:
            st.metric("Revenue from Discounts", f"£{revenue_impact['revenue_from_discounts']:,.2f}")
        
        with col3:
            st.metric("Revenue Growth", f"{revenue_impact['revenue_growth']}%")
        
        with col4:
            st.metric("Profit Margin", f"{revenue_impact['profit_margin']}%")
        
        # Revenue by channel chart
        df = pd.DataFrame(revenue_impact["revenue_by_channel"])
        fig = px.pie(df, values="revenue", names="channel", title="Revenue by Channel")
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()

